# Treza examples

Small, runnable recipes that make AI video with [Treza](https://www.trezalabs.com) from tools you already use: curl, Python, TypeScript, LangChain, n8n, ComfyUI or a crypto wallet. Every recipe follows the same order. Treza quotes the render, the recipe stops if the price is over the cap you set, then it starts the render once at the quoted price, waits for it and downloads the file. Each folder has a short README with what it makes, what it costs and how to run it.

![Treza: a prompt becomes a video](https://raw.githubusercontent.com/treza-labs/treza-labs/main/assets/treza-demo.gif)

## Recipes

| Recipe | Tool | What you get | Typical cost |
| --- | --- | --- | --- |
| [`curl/`](curl) | bash, curl, jq | A 5 second vertical video, or a free picture | about $0.42 for the video\*, $0 for the picture |
| [`python/`](python) | Python and `requests` | A 5 second vertical video | about $0.42\* |
| [`typescript/`](typescript) | Node 20+ and `fetch` | A 5 second vertical video | about $0.42\* |
| [`langchain-colab/`](langchain-colab) | LangChain in a Colab notebook | Your balance and a free picture, then (optional) a 4 second video made by an agent | $0, then about $0.28 |
| [`shorts-from-a-prompt/`](shorts-from-a-prompt) | Python and `requests` | An 18 second vertical Short from one topic: voiceover, three clips, music and captions | about $0.93 |
| [`n8n/`](n8n) | n8n | A 4 second vertical video every morning, handed to an upload step | about $0.28 a day |
| [`comfyui/`](comfyui) | ComfyUI | A free picture, animated into a 4 second vertical clip | about $0.28 |
| [`x402/`](x402) | Node and a wallet holding USDC | A 5 second video, paid per request, with no Treza account | $0.42 in USDC |

Prices are Treza's at the time of writing, on its default models: Veo 3.1 Lite for video (about $0.07 a second with sound, $0.042 without) and Nano Banana for pictures (about $0.06, or free, see below). Every render is quoted before it starts, so the quote, not this table, is the price.

\* Veo 3.1 Lite renders 4, 6 or 8 second takes, so a 5 second request renders 6 seconds. The quote says so. Ask for 4 seconds to pay about $0.28.

## Get a key

1. Sign in at [trezalabs.com](https://www.trezalabs.com).
2. Open [API keys](https://www.trezalabs.com/platform/api-keys) and create a key with the `pipelines:read`, `pipelines:write` and `pipelines:run` permissions.
3. Put it in your environment, not in your code:

   ```bash
   export TREZA_API_KEY="treza_live_..."
   ```

Renders are paid from prepaid credits on your Treza balance. There is no subscription. Add credits under [Settings](https://www.trezalabs.com/platform/settings#billing).

Every account also gets 5 free pictures a day on the default image model (Nano Banana), with or without credits. They come back at midnight UTC. `make_image` quotes a free picture at $0 and says so (`"freeImage": true` and `"freeImagesLeftToday"`), and a price cap never rules one out. A premium image model you name (Nano Banana Pro or GPT Image, for example) is charged as usual, and so is a picture after today's free ones are used. So [`curl/free-image.sh`](curl/free-image.sh) and the first half of the [notebook](langchain-colab) work before you add any credits.

The [x402 recipe](x402) needs no account or key: a wallet pays for each video.

## How the API works

Every Treza tool is one HTTP call:

```
POST https://www.trezalabs.com/api/v1/tools/<tool>
Authorization: Bearer treza_live_...
Content-Type: application/json

{ ...the tool's arguments }
```

These are the same tools as Treza's MCP server (`make_video`, `make_image`, `estimate_run_cost`, `run_pipeline`, `get_run`, `get_credit_balance`, `list_pipelines`, `create_pipeline`, `assemble_video`, `import_media` and more). `GET https://www.trezalabs.com/api/v1/tools` lists them with their input schemas, and there is an [OpenAPI document](https://www.trezalabs.com/api/v1/openapi.json).

A render takes four calls:

1. **Quote.** `make_video` (or `make_image`, or `estimate_run_cost` for a saved pipeline) prepares the render and answers with `estimatedChargeUsd`, `sufficient` (whether your balance covers it), a `pipelineId` and a `quoteId`. Nothing renders yet. With `maxPriceUsd`, a render over that price is refused with code `OVER_BUDGET` and nothing is made.
2. **Check.** Stop if the price is over your cap or `sufficient` is `false`. Nothing has been spent.
3. **Start once.** `run_pipeline` with the `pipelineId` and `quoteId` starts it at the quoted price and returns a `runId`. Sending the same `quoteId` again returns the same run, so a retry never pays twice. A refusal with code `STALE_QUOTE`, `QUOTE_MISMATCH`, `UNKNOWN_QUOTE` or `PRICE_CHANGED` means: quote again.
4. **Wait, then download.** Call `get_run` with the `pipelineId` and `runId` every `pollAfterSec` seconds while its `status` is `running`. A finished run is `success`, `partial`, `error` or `cancelled`, and its `outputs` hold the files (`outputs.video`, `outputs.image`). Those are public links: download them without your key, and use the URL exactly as given.

```bash
curl -s https://www.trezalabs.com/api/v1/tools/make_video \
  -H "Authorization: Bearer $TREZA_API_KEY" -H "Content-Type: application/json" \
  -d '{"prompt": "A red fox trots through fresh snow", "durationSec": 4, "aspectRatio": "9:16", "maxPriceUsd": 1}'
```

```json
{
  "pipelineId": "pipeline_...",
  "quoteId": "q_...",
  "estimatedChargeUsd": 0.28,
  "sufficient": true,
  "balanceUsd": 12.4,
  "model": { "id": "google/veo-3.1-lite", "name": "Veo 3.1 Lite" },
  "durationSec": 4,
  "aspectRatio": "9:16",
  "withAudio": true
}
```

A refusal is an HTTP error with `{"error": "...", "code": "..."}`, worded so a person can act on it: 401 for a bad key, 402 when the balance is short (`INSUFFICIENT_CREDITS`), 403 for a missing permission, 404 for something not found, 429 for too many runs at once, and 400 for the rest.

Every recipe reads `TREZA_BASE_URL` (default `https://www.trezalabs.com`), the same variable Treza's own clients read. The tests use it to point the recipes at a mock.

## Treza in other tools

| Tool | Package | Source |
| --- | --- | --- |
| LangChain and LangGraph | [`langchain-treza`](https://pypi.org/project/langchain-treza/) | [treza-labs/langchain-treza](https://github.com/treza-labs/langchain-treza) |
| Vercel AI SDK | [`@treza/ai-sdk`](https://www.npmjs.com/package/@treza/ai-sdk) | [treza-labs/treza-ai-sdk](https://github.com/treza-labs/treza-ai-sdk) |
| LlamaIndex | [`llama-index-tools-treza`](https://pypi.org/project/llama-index-tools-treza/) | [treza-labs/llama-index-tools-treza](https://github.com/treza-labs/llama-index-tools-treza) |
| CrewAI | [`crewai-treza`](https://pypi.org/project/crewai-treza/) | [treza-labs/crewai-treza](https://github.com/treza-labs/crewai-treza) |
| Langflow | [`lfx-treza`](https://pypi.org/project/lfx-treza/) | [treza-labs/lfx-treza](https://github.com/treza-labs/lfx-treza) |
| n8n | [`@treza/n8n-nodes-treza`](https://www.npmjs.com/package/@treza/n8n-nodes-treza) | [treza-labs/n8n-nodes-treza](https://github.com/treza-labs/n8n-nodes-treza) |
| ComfyUI | [`treza` on the Comfy Registry](https://registry.comfy.org/nodes/treza) | [treza-labs/treza-comfyui](https://github.com/treza-labs/treza-comfyui) |
| Dify | [Dify Marketplace](https://marketplace.dify.ai/plugins/treza-labs/treza) | [treza-labs/treza-dify-plugin](https://github.com/treza-labs/treza-dify-plugin) |
| Zapier | [Treza on Zapier](https://www.trezalabs.com/integrations/zapier) | [treza-labs/treza-zapier](https://github.com/treza-labs/treza-zapier) |
| x402 (pay per video with a wallet) | | [treza-labs/x402-video-example](https://github.com/treza-labs/x402-video-example) |
| Claude, ChatGPT, Cursor and other MCP clients | MCP server at `https://www.trezalabs.com/api/mcp` | [treza-labs/treza-plugin](https://github.com/treza-labs/treza-plugin) |
| GitHub Actions | | [treza-labs/render-video](https://github.com/treza-labs/render-video) |

Setup steps for each of them are at [trezalabs.com/integrations](https://www.trezalabs.com/integrations).

## Tests

```bash
python3 tests/run_tests.py
```

This runs every recipe against [`tests/mock_treza.py`](tests/mock_treza.py), a small local stand-in for Treza's API that answers with the same fields and refusal codes. It needs no key and spends nothing. See [`tests/README.md`](tests/README.md) for what each test needs.

## License

[MIT](LICENSE). Issues and questions: [GitHub issues](https://github.com/treza-labs/treza-examples/issues) or hello@trezalabs.com.
