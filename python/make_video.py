"""Make a short AI video with Treza's REST API. Needs only `requests`.

The order every Treza render follows:
  1. make_video prices the clip and returns a quoteId. Nothing renders yet.
  2. Stop if the price is over --max-cost or the balance does not cover it.
  3. run_pipeline starts the render once, at the quoted price.
  4. get_run until it finishes, then download the file.

    pip install requests
    export TREZA_API_KEY=treza_live_...
    python make_video.py "A paper boat drifts down a rain-filled gutter at dawn"
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Any

import requests

BASE_URL = (os.environ.get("TREZA_BASE_URL") or "https://www.trezalabs.com").rstrip("/")
TOP_UP_URL = "https://www.trezalabs.com/platform/settings"
# A quote that no longer matches (another render took its place, or the price moved): quote again.
QUOTE_AGAIN = {"STALE_QUOTE", "QUOTE_MISMATCH", "UNKNOWN_QUOTE", "PRICE_CHANGED"}


class Refused(Exception):
    """Treza said no. The message says why, and whether anything was spent."""

    def __init__(self, message: str, code: str | None = None):
        super().__init__(message)
        self.code = code


def treza(tool: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Call one Treza tool: POST /api/v1/tools/<tool> with the arguments as JSON."""
    response = requests.post(
        f"{BASE_URL}/api/v1/tools/{tool}",
        json=args or {},
        headers={"Authorization": f"Bearer {os.environ['TREZA_API_KEY']}", "User-Agent": "treza-examples-python/1.0"},
        timeout=(10, 120),
    )
    try:
        body = response.json()
    except ValueError:
        body = {"error": response.text[:300]}
    if response.status_code >= 400:
        raise Refused(f"{tool}: {body.get('error') or f'HTTP {response.status_code}'}", body.get("code"))
    return body


def model_name(quote: dict[str, Any]) -> str:
    model = quote.get("model")
    return (model.get("name") or model.get("id")) if isinstance(model, dict) else str(model)


def quote_and_start(args: dict[str, Any], max_cost: float) -> tuple[dict[str, Any], dict[str, Any]]:
    """Price the clip, check it against the cap and the balance, then start it once."""
    for _ in range(3):
        quote = treza("make_video", {**args, "maxPriceUsd": max_cost})  # over the cap: refused, OVER_BUDGET
        price = float(quote["estimatedChargeUsd"])
        print(f"Quote: {quote['durationSec']}s {quote['aspectRatio']} on {model_name(quote)} for ${price:.2f}")
        if quote.get("requestedDurationSec"):
            print(f"       (the model renders fixed lengths, so it makes {quote['durationSec']}s for the {args['durationSec']}s you asked for)")
        if price > max_cost:
            raise Refused(f"This clip costs ${price:.2f}, over --max-cost ${max_cost:.2f}. Nothing was spent.")
        if quote.get("sufficient") is False:
            raise Refused(
                f"Your balance is ${float(quote.get('balanceUsd') or 0):.2f}. Nothing was spent. "
                f"Add credits at {quote.get('topUpUrl') or TOP_UP_URL}"
            )
        try:
            # The quoteId makes the start safe to retry: the same quoteId returns the same run.
            run = treza("run_pipeline", {"pipelineId": quote["pipelineId"], "quoteId": quote["quoteId"]})
            return quote, run
        except Refused as refusal:
            if refusal.code not in QUOTE_AGAIN:
                raise
            print("The quote went stale. Quoting again.")
    raise Refused("Treza's quote kept changing. Nothing was spent. Try again.")


def wait_for(pipeline_id: str, run_id: str, max_wait: float) -> dict[str, Any]:
    """Poll get_run until the run finishes, waiting as long as Treza suggests (2 to 10 s)."""
    started = time.monotonic()
    while True:
        run = treza("get_run", {"pipelineId": pipeline_id, "runId": run_id})
        if run.get("status") != "running":
            return run
        elapsed = time.monotonic() - started
        if elapsed > max_wait:
            raise Refused(
                f"Still rendering after {elapsed:.0f}s. It keeps going on Treza: "
                f"call get_run with pipelineId {pipeline_id} and runId {run_id} later."
            )
        print(f"  still rendering ({elapsed:.0f}s)")
        time.sleep(min(max(float(run.get("pollAfterSec") or 3), 2), 10))


def finished_url(run: dict[str, Any], key: str) -> str:
    """The file a finished run made: the named output, or else the first link among the outputs."""
    if run.get("status") not in ("success", "partial"):
        reasons = [run.get("statusNote"), run.get("refusalNote")]
        reasons += [f"{n.get('label') or n.get('type')}: {n['error']}" for n in run.get("nodes") or [] if n.get("error")]
        raise Refused(f"The render stopped ({run.get('status')}). " + " ".join(r for r in reasons if r))
    outputs = run.get("outputs") or {}
    url = outputs.get(key) or next((v for v in outputs.values() if isinstance(v, str) and v.startswith("http")), None)
    if not url:
        raise Refused("The run finished but returned no file.")
    return url


def download(url: str, path: str) -> int:
    """Finished files are public links: no API key, and the URL is used exactly as given."""
    response = requests.get(url, timeout=(10, 300))
    response.raise_for_status()
    with open(path, "wb") as f:
        f.write(response.content)
    return len(response.content)


def main() -> int:
    parser = argparse.ArgumentParser(description="Make a short AI video with Treza.")
    parser.add_argument("prompt", nargs="?", default="A paper boat drifts down a rain-filled street gutter at dawn, low angle, soft reflections, slow push in")
    parser.add_argument("--seconds", type=float, default=5, help="length to ask for (default 5)")
    parser.add_argument("--aspect", default="9:16", choices=["16:9", "9:16", "1:1"], help="shape (default 9:16)")
    parser.add_argument("--max-cost", type=float, default=1.00, help="the most this render may cost, in USD (default 1.00)")
    parser.add_argument("--model", help="a Treza video model id; leave out for Treza's default (Veo 3.1 Lite)")
    parser.add_argument("--no-audio", action="store_true", help="a silent clip, which costs less")
    parser.add_argument("--out", default="video.mp4", help="where to save it (default video.mp4)")
    parser.add_argument("--max-wait", type=float, default=900, help="seconds to wait for the render (default 900)")
    opts = parser.parse_args()

    if not os.environ.get("TREZA_API_KEY"):
        print("Set TREZA_API_KEY. Make a key at https://www.trezalabs.com/platform/api-keys", file=sys.stderr)
        return 1
    if opts.max_cost <= 0:
        print("--max-cost must be more than 0.", file=sys.stderr)
        return 1

    args: dict[str, Any] = {"prompt": opts.prompt, "durationSec": opts.seconds, "aspectRatio": opts.aspect}
    if opts.model:
        args["model"] = opts.model
    if opts.no_audio:
        args["withAudio"] = False

    try:
        quote, run = quote_and_start(args, opts.max_cost)
        print(f"Rendering (run {run['runId']})...")
        finished = wait_for(quote["pipelineId"], run["runId"], opts.max_wait)
        url = finished_url(finished, "video")
        size = download(url, opts.out)
    except Refused as refusal:
        print(refusal, file=sys.stderr)
        return 1
    print(f"Saved {opts.out} ({size} bytes). Quoted price: ${float(quote['estimatedChargeUsd']):.2f}.")
    print(f"Link: {url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
