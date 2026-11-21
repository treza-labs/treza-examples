/**
 * Make a short AI video with Treza's REST API. Node 20+, no dependencies: just fetch.
 *
 * The order every Treza render follows:
 *   1. make_video prices the clip and returns a quoteId. Nothing renders yet.
 *   2. Stop if the price is over --max-cost or the balance does not cover it.
 *   3. run_pipeline starts the render once, at the quoted price.
 *   4. get_run until it finishes, then download the file.
 *
 *   export TREZA_API_KEY=treza_live_...
 *   npx tsx make-video.ts "A paper boat drifts down a rain-filled gutter at dawn"
 */
import { writeFile } from "node:fs/promises";
import { parseArgs } from "node:util";

type Data = Record<string, any>;

const BASE_URL = (process.env.TREZA_BASE_URL || "https://www.trezalabs.com").replace(/\/+$/, "");
const TOP_UP_URL = "https://www.trezalabs.com/platform/settings";
// A quote that no longer matches (another render took its place, or the price moved): quote again.
const QUOTE_AGAIN = new Set(["STALE_QUOTE", "QUOTE_MISMATCH", "UNKNOWN_QUOTE", "PRICE_CHANGED"]);

/** Treza said no. The message says why, and whether anything was spent. */
class Refused extends Error {
  code?: string;
  constructor(message: string, code?: string) {
    super(message);
    this.code = code;
  }
}

/** Call one Treza tool: POST /api/v1/tools/<tool> with the arguments as JSON. */
async function treza(tool: string, args: Data = {}): Promise<Data> {
  const response = await fetch(`${BASE_URL}/api/v1/tools/${tool}`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${process.env.TREZA_API_KEY}`,
      "Content-Type": "application/json",
      "User-Agent": "treza-examples-typescript/1.0",
    },
    body: JSON.stringify(args),
  });
  const text = await response.text();
  let body: Data;
  try {
    body = JSON.parse(text);
  } catch {
    body = { error: text.slice(0, 300) };
  }
  if (response.status >= 400) throw new Refused(`${tool}: ${body.error || `HTTP ${response.status}`}`, body.code);
  return body;
}

const usd = (n: unknown) => `$${Number(n).toFixed(2)}`;
const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
const modelName = (quote: Data) =>
  quote.model && typeof quote.model === "object" ? quote.model.name || quote.model.id : String(quote.model);

/** Price the clip, check it against the cap and the balance, then start it once. */
async function quoteAndStart(args: Data, maxCost: number): Promise<{ quote: Data; run: Data }> {
  for (let attempt = 0; attempt < 3; attempt++) {
    const quote = await treza("make_video", { ...args, maxPriceUsd: maxCost }); // over the cap: refused, OVER_BUDGET
    const price = Number(quote.estimatedChargeUsd);
    console.log(`Quote: ${quote.durationSec}s ${quote.aspectRatio} on ${modelName(quote)} for ${usd(price)}`);
    if (quote.requestedDurationSec) {
      console.log(`       (the model renders fixed lengths, so it makes ${quote.durationSec}s for the ${args.durationSec}s you asked for)`);
    }
    if (!(price <= maxCost)) throw new Refused(`This clip costs ${usd(price)}, over --max-cost ${usd(maxCost)}. Nothing was spent.`);
    if (quote.sufficient === false) {
      throw new Refused(`Your balance is ${usd(quote.balanceUsd ?? 0)}. Nothing was spent. Add credits at ${quote.topUpUrl || TOP_UP_URL}`);
    }
    try {
      // The quoteId makes the start safe to retry: the same quoteId returns the same run.
      const run = await treza("run_pipeline", { pipelineId: quote.pipelineId, quoteId: quote.quoteId });
      return { quote, run };
    } catch (err) {
      if (!(err instanceof Refused) || !QUOTE_AGAIN.has(err.code ?? "")) throw err;
      console.log("The quote went stale. Quoting again.");
    }
  }
  throw new Refused("Treza's quote kept changing. Nothing was spent. Try again.");
}

/** Poll get_run until the run finishes, waiting as long as Treza suggests (2 to 10 s). */
async function waitFor(pipelineId: string, runId: string, maxWaitSec: number): Promise<Data> {
  const started = Date.now();
  for (;;) {
    const run = await treza("get_run", { pipelineId, runId });
    if (run.status !== "running") return run;
    const elapsed = Math.round((Date.now() - started) / 1000);
    if (elapsed > maxWaitSec) {
      throw new Refused(`Still rendering after ${elapsed}s. It keeps going on Treza: call get_run with pipelineId ${pipelineId} and runId ${runId} later.`);
    }
    console.log(`  still rendering (${elapsed}s)`);
    await sleep(Math.min(Math.max(Number(run.pollAfterSec) || 3, 2), 10) * 1000);
  }
}

/** The file a finished run made: the named output, or else the first link among the outputs. */
function finishedUrl(run: Data, key: string): string {
  if (run.status !== "success" && run.status !== "partial") {
    const broken = (run.nodes ?? []).filter((n: Data) => n.error).map((n: Data) => `${n.label || n.type}: ${n.error}`);
    const reasons = [run.statusNote, run.refusalNote, ...broken].filter(Boolean).join(" ");
    throw new Refused(`The render stopped (${run.status}). ${reasons}`);
  }
  const outputs: Data = run.outputs ?? {};
  const url = outputs[key] ?? Object.values(outputs).find((v) => typeof v === "string" && /^https?:\/\//.test(v));
  if (!url) throw new Refused("The run finished but returned no file.");
  return url;
}

/** Finished files are public links: no API key, and the URL is used exactly as given. */
async function download(url: string, path: string): Promise<number> {
  const response = await fetch(url);
  if (!response.ok) throw new Refused(`The download failed (HTTP ${response.status}): ${url}`);
  const bytes = Buffer.from(await response.arrayBuffer());
  await writeFile(path, bytes);
  return bytes.length;
}

async function main(): Promise<number> {
  const { values, positionals } = parseArgs({
    allowPositionals: true,
    options: {
      seconds: { type: "string", default: "5" },
      aspect: { type: "string", default: "9:16" },
      "max-cost": { type: "string", default: "1.00" },
      model: { type: "string" },
      "no-audio": { type: "boolean", default: false },
      out: { type: "string", default: "video.mp4" },
      "max-wait": { type: "string", default: "900" },
    },
  });
  if (!process.env.TREZA_API_KEY) {
    console.error("Set TREZA_API_KEY. Make a key at https://www.trezalabs.com/platform/api-keys");
    return 1;
  }
  const maxCost = Number(values["max-cost"]);
  if (!(maxCost > 0)) {
    console.error("--max-cost must be more than 0.");
    return 1;
  }
  const args: Data = {
    prompt: positionals.join(" ") || "A paper boat drifts down a rain-filled street gutter at dawn, low angle, soft reflections, slow push in",
    durationSec: Number(values.seconds),
    aspectRatio: values.aspect,
    ...(values.model ? { model: values.model } : {}),
    ...(values["no-audio"] ? { withAudio: false } : {}),
  };

  try {
    const { quote, run } = await quoteAndStart(args, maxCost);
    console.log(`Rendering (run ${run.runId})...`);
    const finished = await waitFor(quote.pipelineId, run.runId, Number(values["max-wait"]));
    const url = finishedUrl(finished, "video");
    const size = await download(url, values.out!);
    console.log(`Saved ${values.out} (${size} bytes). Quoted price: ${usd(quote.estimatedChargeUsd)}.`);
    console.log(`Link: ${url}`);
    return 0;
  } catch (err) {
    if (err instanceof Refused) {
      console.error(err.message);
      return 1;
    }
    throw err;
  }
}

process.exitCode = await main();
