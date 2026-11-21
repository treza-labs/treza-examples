# TypeScript

[`make-video.ts`](make-video.ts) makes a short video with Treza's REST API in one file, for Node 20 or newer. It uses the built-in `fetch` and no packages. It quotes the clip, stops if the price is over `--max-cost` or your balance is short, starts it once with the quote, waits and saves the file.

**Cost:** about $0.42 for the default 5 second 9:16 clip with sound. Treza's default model, Veo 3.1 Lite, renders 4, 6 or 8 second takes, so 5 seconds renders 6. `--seconds 4` is about $0.28.

## Run

```bash
export TREZA_API_KEY="treza_live_..."   # see ../README.md#get-a-key
npx tsx make-video.ts "A paper boat drifts down a rain-filled street gutter at dawn, low angle"
```

On Node 23.6 or newer you can skip `tsx`: `node make-video.ts "..."`. Or install the dev tools once and use the scripts: `npm install`, then `npm start -- "..."` and `npm run typecheck`.

| Option | Default | What it does |
| --- | --- | --- |
| `--seconds` | `5` | Length to ask for |
| `--aspect` | `9:16` | `16:9`, `9:16` or `1:1` |
| `--max-cost` | `1.00` | The most this render may cost, in USD |
| `--model` | Treza's default | A video model id, such as `google/veo-3.1-lite` |
| `--no-audio` | off | A silent clip, which costs less |
| `--out` | `video.mp4` | Where to save it |
| `--max-wait` | `900` | Seconds to wait before leaving the render to finish on Treza |

`TREZA_BASE_URL` changes Treza's address (the tests point it at a mock).

## Expected output

```
Quote: 6s 9:16 on Veo 3.1 Lite for $0.42
       (the model renders fixed lengths, so it makes 6s for the 5s you asked for)
Rendering (run run_...)...
  still rendering (0s)
  still rendering (10s)
  ...
Saved video.mp4 (... bytes). Quoted price: $0.42.
Link: https://media.trezalabs.com/...
```

A refusal (over the cap, a short balance, a bad key) prints Treza's reason and exits with code 1, with nothing spent.

To give the same tools to a model in the Vercel AI SDK, use [`@treza/ai-sdk`](https://github.com/treza-labs/treza-ai-sdk).
