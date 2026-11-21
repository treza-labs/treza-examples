# Python

[`make_video.py`](make_video.py) makes a short video with Treza's REST API in one file, with `requests` as its only dependency. It quotes the clip, stops if the price is over `--max-cost` or your balance is short, starts it once with the quote, waits and saves the file.

**Cost:** about $0.42 for the default 5 second 9:16 clip with sound. Treza's default model, Veo 3.1 Lite, renders 4, 6 or 8 second takes, so 5 seconds renders 6. `--seconds 4` is about $0.28, and `--no-audio` takes it to about $0.17 for 4 seconds.

## Run

```bash
pip install -r requirements.txt
export TREZA_API_KEY="treza_live_..."   # see ../README.md#get-a-key
python make_video.py "A paper boat drifts down a rain-filled street gutter at dawn, low angle"
```

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

A refusal (over the cap, a short balance, a bad key) prints Treza's reason and exits with code 1, with nothing spent. If the quote goes stale before the start, the script quotes again, up to three times.

For an agent rather than a script, use [`langchain-treza`](https://github.com/treza-labs/langchain-treza), which wraps the same flow as LangChain tools.
