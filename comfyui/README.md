# ComfyUI

[`treza_free_picture_to_vertical_clip.json`](treza_free_picture_to_vertical_clip.json) is a ComfyUI workflow that uses the [Treza nodes](https://github.com/treza-labs/treza-comfyui):

**Treza Generate Image** (a 9:16 picture, `max_cost_usd` 0.01) → **Preview Image**, and → **Treza Generate Video** (`first_frame`: the clip opens on the picture; 4 seconds, 9:16, `max_cost_usd` 0.50) → **Save Video**.

The renders run on Treza's servers, so they need no GPU or model downloads.

**Cost:** about $0.28.

- The picture is one of today's 5 free pictures, so it costs $0. Its `max_cost_usd` of 0.01 holds it to a free one: once they are used up, the node stops with nothing spent. Set it to 0.10 to pay for a picture (about $0.06).
- The clip is 4 seconds with sound on Veo 3.1 Lite, about $0.28. Its `max_cost_usd` of 0.50 is the most it may cost.

## Run

1. Install the pack: `git clone https://github.com/treza-labs/treza-comfyui treza` inside `ComfyUI/custom_nodes`. It needs ComfyUI 0.3.45 or newer. ComfyUI-Manager and comfy-cli can't install it yet, because the Comfy Registry is holding versions 0.1.0 and 0.1.1 for review; searching for **Treza** in ComfyUI-Manager will work again once the Registry lists them.
2. Make a Treza key at https://www.trezalabs.com/platform/api-keys with the `pipelines:read`, `pipelines:write` and `pipelines:run` permissions. Give it to ComfyUI as the `TREZA_API_KEY` environment variable, or as the only line of `user/treza_api_key.txt`, then restart ComfyUI. The key is never saved in the workflow.
3. Drag `treza_free_picture_to_vertical_clip.json` onto the ComfyUI canvas, or open it from **Workflow → Open**.
4. Edit the two prompts and press **Run**.

## Expected output

The picture shows in **Preview Image** after under a minute. The clip takes one to five minutes and is saved by **Save Video** under `ComfyUI/output/video/treza-fox_*.mp4`. Each Treza node also outputs the file's `url`, the `price_usd` Treza charged and the `model`.

ComfyUI reuses a node's last result while its settings are unchanged, so running the graph again does not pay twice. Change `seed` to render again. ComfyUI's Cancel button also cancels the render on Treza.
