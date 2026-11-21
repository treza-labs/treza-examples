// Buy one AI video with a wallet: no Treza account, no API key. The payment is the credential.
// npm install @x402/fetch @x402/evm viem tsx   then   PRIVATE_KEY=0x... npx tsx buy-video.ts
import { writeFile } from "node:fs/promises";
import { wrapFetchWithPaymentFromConfig } from "@x402/fetch";
import { ExactEvmScheme } from "@x402/evm";
import { privateKeyToAccount } from "viem/accounts";

const wallet = privateKeyToAccount(process.env.PRIVATE_KEY as `0x${string}`); // a small hot wallet holding USDC on Base
const pay = wrapFetchWithPaymentFromConfig(fetch, {
  schemes: [{ network: "eip155:8453", client: new ExactEvmScheme(wallet) }],
  spendControls: { maxAmountPerPayment: "$1" }, // the default 5 s clip is $0.42
});

const res = await pay(process.env.X402_VIDEO_ENDPOINT ?? "https://www.trezalabs.com/api/x402/video", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ prompt: "a paper boat drifting down a rain-filled gutter at dawn", aspectRatio: "9:16" }),
});
if (!res.ok) throw new Error(`Purchase failed (${res.status}): ${await res.text()}`);
const order = await res.json(); // answers within 45 s: the video, or status "running" and a statusUrl
let status = order;
while (status.status === "running") {
  await new Promise((r) => setTimeout(r, status.pollAfterMs ?? 15_000));
  status = await (await fetch(order.statusUrl)).json(); // polling is free: the render is paid for
}
if (!status.video) throw new Error(`No video (${status.status}). ${status.message ?? ""} ${status.retryUrl ?? ""}`);
await writeFile("video.mp4", Buffer.from(await (await fetch(status.video)).arrayBuffer()));
console.log(`Paid $${order.paidUsd} USDC for ${order.seconds}s on ${order.model}. Saved video.mp4`);
