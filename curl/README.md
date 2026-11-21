# curl

Two shell scripts that call Treza's REST API with `curl` and `jq`. They show the whole flow with nothing hidden: quote, check the price, start once, wait, download.

| Script | What it makes | Cost |
| --- | --- | --- |
| [`make-video.sh`](make-video.sh) | A 5 second 9:16 video with sound, saved as `video.mp4` | about $0.42 |
| [`free-image.sh`](free-image.sh) | One picture, saved as `image.png` | $0: one of today's 5 free pictures |

Treza's default video model, Veo 3.1 Lite, renders 4, 6 or 8 second takes, so the 5 second request renders 6 seconds, at about $0.07 a second. `CLIP_SECONDS=4` costs about $0.28. The quote always prints what will render and its price before anything starts.

`free-image.sh` renders only a free picture by default (`MAX_COST=0`). Once today's free pictures are used up it stops and spends nothing. `MAX_COST=0.10` lets it pay for one (about $0.06).

## Run

You need bash, curl and jq (`brew install jq` or `apt install jq`), and a key from [Get a key](../README.md#get-a-key).

```bash
export TREZA_API_KEY="treza_live_..."
./make-video.sh "A paper boat drifts down a rain-filled street gutter at dawn, low angle"
./free-image.sh "A lighthouse on a sea cliff at golden hour, loose watercolor"
```

## Settings

Set these as environment variables, for example `ASPECT=16:9 ./make-video.sh`.

| Variable | Default | What it does |
| --- | --- | --- |
| `CLIP_SECONDS` | `5` | Length to ask for (video) |
| `ASPECT` | `9:16` (video), `16:9` (picture) | Shape: `16:9`, `9:16` or `1:1` for video; also `4:5`, `3:2` and others for pictures |
| `MAX_COST` | `1.00` (video), `0` (picture) | The most this render may cost, in USD. Nothing over it starts |
| `OUT` | `video.mp4`, `image.<ext>` | Where to save the file |
| `MAX_WAIT` | `900` | Seconds to wait for the video before leaving it to finish on Treza |
| `TREZA_BASE_URL` | `https://www.trezalabs.com` | Treza's address. The tests point it at a mock |

## Expected output

```
$ ./make-video.sh "A paper boat drifts down a rain-filled street gutter at dawn, low angle"
Asking Treza for a quote...
Quote: 6s 9:16 on Veo 3.1 Lite for $0.42
       (the model renders fixed lengths, so it makes 6s for the 5s you asked for)
Rendering (run run_...)...
  still rendering (0s)
  still rendering (10s)
  ...
Saved video.mp4 (... bytes). Quoted price: $0.42.
Link: https://media.trezalabs.com/...

$ ./free-image.sh "A lighthouse on a sea cliff at golden hour, loose watercolor"
Free: 5 free pictures left today (this one included). Nothing will be charged.
Drawing (run run_...)...
Saved image.png (... bytes).
Link: https://media.trezalabs.com/...
```

Videos usually take one to five minutes and pictures under a minute. If the price is over `MAX_COST`, the balance is short or the key is wrong, the script says so and exits with nothing spent.
