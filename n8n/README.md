# n8n

[`daily-vertical-video.json`](daily-vertical-video.json) is an n8n workflow that makes a vertical video every morning with the [`@treza/n8n-nodes-treza`](https://github.com/treza-labs/n8n-nodes-treza) community node:

**Every morning** (Schedule Trigger, 9:00 in the workflow's time zone) → **Today's prompt** (Edit Fields: picks one of three prompts by day of the year) → **Generate the video** (Treza, Video → Generate: 4 seconds, 9:16, Max Cost $1, Download Output on) → **Upload the video (replace me)** (No Operation, a placeholder for your upload).

**Cost:** about $0.28 a run on Treza's default model, Veo 3.1 Lite, so about $8.40 for 30 days. Before each render the node gets Treza's quote. If the price is over Max Cost ($1) or your balance does not cover it, the item stops and nothing is charged. The render then starts once, at the quoted price.

## Import it

1. Install the node: in n8n, **Settings → Community Nodes → Install**, and enter `@treza/n8n-nodes-treza`. (On n8n Cloud it is a verified node: search for Treza in the nodes panel.)
2. Make a Treza key at https://www.trezalabs.com/platform/api-keys with the `pipelines:read`, `pipelines:write` and `pipelines:run` permissions.
3. **Workflows → Import from File** (or paste the JSON onto the canvas) and choose `daily-vertical-video.json`.
4. Open **Generate the video**, create a **Treza API** credential and paste the key. The credential test checks it against your balance.
5. Edit the prompts in **Today's prompt**.
6. Replace **Upload the video (replace me)** with your upload: YouTube (Upload a Video), Google Drive (Upload File), S3, or an HTTP Request. The clip is in the binary field `video`.
7. Run it once with **Execute Workflow**, then turn the workflow on.

## Expected output

**Generate the video** outputs one item with the clip as binary data in `video`, and JSON like:

```json
{
  "url": "https://media.trezalabs.com/...mp4",
  "status": "success",
  "estimatedChargeUsd": 0.28,
  "model": "google/veo-3.1-lite",
  "durationMs": 61000,
  "outputs": { "video": "https://media.trezalabs.com/...mp4" },
  "runId": "...",
  "pipelineId": "pipeline_..."
}
```

A render takes one to five minutes. The node waits up to 30 minutes (**Timeout**). A render still going then comes out with `timedOut: true` instead of failing, so Retry On Fail never pays for a second one. It keeps going on Treza, and **Run → Wait for Completion** picks it up later.

More workflows, including a Google Sheets row to a video and three shots to a music video, are in the node's [`examples/`](https://github.com/treza-labs/n8n-nodes-treza/tree/main/examples) folder.
