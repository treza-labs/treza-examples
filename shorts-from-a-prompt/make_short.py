"""Turn one topic into a narrated, captioned vertical Short with Treza. Needs only `requests`.

    topic  ->  script: a voiceover, read aloud, and three shot descriptions (one small pipeline)
           ->  three vertical clips (make_video)
           ->  one 1080x1920 Short: the clips, the voiceover, a composed music bed and captions (assemble_video)

Every paid step is priced before it starts. Without --yes the script prints the quote and
spends nothing.

    pip install requests
    export TREZA_API_KEY=treza_live_...
    python make_short.py "how octopuses taste with their arms"         # the quote only
    python make_short.py "how octopuses taste with their arms" --yes   # make it
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from typing import Any, Callable

import requests

BASE_URL = (os.environ.get("TREZA_BASE_URL") or "https://www.trezalabs.com").rstrip("/")
TOP_UP_URL = "https://www.trezalabs.com/platform/settings"
QUOTE_AGAIN = {"STALE_QUOTE", "QUOTE_MISMATCH", "UNKNOWN_QUOTE", "PRICE_CHANGED"}

# The script step is a pipeline saved in your account under this name, made on the first run
# and reused after that. A new version of this recipe gets a new name.
SCRIPT_PIPELINE = "Short script (treza-examples v1)"

VOICEOVER_PROMPT = (
    "You write voiceovers for vertical videos that run 18 seconds. Given a topic, write one voiceover "
    "of 35 to 45 words that a narrator reads in about 15 seconds: a hook in the first sentence, then two "
    "or three plain facts. Reply with the voiceover text only: no title, no quotation marks, no stage "
    "directions, no emoji."
)
SHOTS_PROMPT = (
    "You plan the pictures for a vertical video. You get its voiceover. Write exactly three shot "
    "descriptions that illustrate it in order, one per line, with no numbers, bullets or blank lines. "
    "Each is one sentence a video model can render: the subject, what it does, the setting, the light "
    "and the camera move. No words on screen, no logos, no real people."
)


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
        headers={"Authorization": f"Bearer {os.environ['TREZA_API_KEY']}", "User-Agent": "treza-examples-shorts/1.0"},
        timeout=(10, 120),
    )
    try:
        body = response.json()
    except ValueError:
        body = {"error": response.text[:300]}
    if response.status_code >= 400:
        raise Refused(f"{tool}: {body.get('error') or f'HTTP {response.status_code}'}", body.get("code"))
    return body


# ------------------------------------------------------------------ the script step


def script_graph() -> dict[str, list[dict[str, Any]]]:
    """Topic -> voiceover (text) -> spoken voiceover and three shot descriptions."""
    nodes = [
        {"id": "topic", "type": "text-input", "label": "Topic", "config": {"value": ""}},
        {"id": "writer", "type": "ai-model", "label": "Write the voiceover", "config": {"systemPrompt": VOICEOVER_PROMPT, "maxTokens": 300}},
        {"id": "voice", "type": "tts", "label": "Read it aloud"},
        {"id": "director", "type": "ai-model", "label": "Plan three shots", "config": {"systemPrompt": SHOTS_PROMPT, "maxTokens": 300}},
        {"id": "script", "type": "output", "label": "Voiceover text", "config": {"name": "script"}},
        {"id": "narration", "type": "output", "label": "Voiceover audio", "config": {"name": "narration"}},
        {"id": "shots", "type": "output", "label": "Shots", "config": {"name": "shots"}},
    ]
    wires = [
        ("topic", "out", "writer", "prompt"),
        ("writer", "completion", "voice", "text"),
        ("writer", "completion", "director", "prompt"),
        ("writer", "completion", "script", "in"),
        ("voice", "audio", "narration", "in"),
        ("director", "completion", "shots", "in"),
    ]
    edges = [{"source": s, "sourceHandle": sh, "target": t, "targetHandle": th} for s, sh, t, th in wires]
    return {"nodes": nodes, "edges": edges}


def script_pipeline_id() -> str:
    """The script pipeline in your account: found by name, or created (free) on the first run."""
    for pipeline in treza("list_pipelines").get("pipelines", []):
        if pipeline.get("name") == SCRIPT_PIPELINE:
            return pipeline["id"]
    created = treza(
        "create_pipeline",
        {"name": SCRIPT_PIPELINE, "description": "Writes and reads a voiceover for make_short.py (treza-examples).", **script_graph()},
    )
    print(f'Saved the pipeline "{SCRIPT_PIPELINE}" in your Treza account. Later runs reuse it.')
    return created["id"]


def parse_shots(text: str, topic: str) -> list[str]:
    """Three shot prompts from the director's reply, minus any numbering it added anyway."""
    shots = [re.sub(r"^\s*(?:shot\s*\d+\s*[:.)-]|\d+\s*[.):-]|[-*•])\s*", "", line, flags=re.I).strip() for line in text.splitlines()]
    shots = [s for s in shots if len(s) > 10][:3]
    while len(shots) < 3:
        shots.append(f"{topic}, cinematic vertical shot, soft natural light, slow camera move")
    return shots


# ------------------------------------------------------------------ quotes and runs


def start_quoted(quote: Callable[[], dict[str, Any]], budget: float, inputs: dict[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Quote, check the price against what is left of the budget, then start the run once."""
    for _ in range(3):
        quoted = quote()
        price = float(quoted["estimatedChargeUsd"])
        if price > budget + 1e-9:
            raise Refused(f"This step costs ${price:.2f}, more than the ${budget:.2f} left of --max-cost.")
        if quoted.get("sufficient") is False:
            raise Refused(f"Your balance does not cover ${price:.2f}. Add credits at {quoted.get('topUpUrl') or TOP_UP_URL}")
        start = {"pipelineId": quoted["pipelineId"], "quoteId": quoted["quoteId"], **({"inputs": inputs} if inputs else {})}
        try:
            return quoted, treza("run_pipeline", start)
        except Refused as refusal:
            if refusal.code not in QUOTE_AGAIN:
                raise
    raise Refused("Treza's quote kept changing. Try again.")


def wait_for(pipeline_id: str, run_id: str, what: str, max_wait: float = 1200) -> dict[str, Any]:
    """Poll get_run until the run finishes, waiting as long as Treza suggests (2 to 10 s)."""
    started = time.monotonic()
    while True:
        run = treza("get_run", {"pipelineId": pipeline_id, "runId": run_id})
        status = run.get("status")
        if status in ("success", "partial"):
            return run
        if status != "running":
            reasons = [run.get("statusNote"), run.get("refusalNote")]
            reasons += [f"{n.get('label') or n.get('type')}: {n['error']}" for n in run.get("nodes") or [] if n.get("error")]
            raise Refused(f"{what} stopped ({status}). " + " ".join(r for r in reasons if r))
        if time.monotonic() - started > max_wait:
            raise Refused(f"{what} is still rendering. It keeps going on Treza: get_run with pipelineId {pipeline_id} and runId {run_id}.")
        time.sleep(min(max(float(run.get("pollAfterSec") or 3), 2), 10))


def download(url: str, path: str) -> int:
    """Finished files are public links: no API key, and the URL is used exactly as given."""
    response = requests.get(url, timeout=(10, 300))
    response.raise_for_status()
    with open(path, "wb") as f:
        f.write(response.content)
    return len(response.content)


# ------------------------------------------------------------------ main


def main() -> int:
    parser = argparse.ArgumentParser(description="Turn a topic into a narrated, captioned vertical Short with Treza.")
    parser.add_argument("topic", help='what the Short is about, e.g. "how octopuses taste with their arms"')
    parser.add_argument("--yes", action="store_true", help="make it. Without this, only the quote is shown")
    parser.add_argument("--max-cost", type=float, default=2.00, help="the most the whole Short may cost, in USD (default 2.00)")
    parser.add_argument("--seconds", type=int, default=6, choices=[6, 8], help="length of each of the three clips (default 6)")
    parser.add_argument("--music", default="warm cinematic underscore, soft piano and strings, gentle pulse, no vocals", help="the music bed to compose")
    parser.add_argument("--out", default="short.mp4", help="where to save it (default short.mp4)")
    opts = parser.parse_args()
    if not os.environ.get("TREZA_API_KEY"):
        print("Set TREZA_API_KEY. Make a key at https://www.trezalabs.com/platform/api-keys", file=sys.stderr)
        return 1
    topic = opts.topic.strip()

    def clip_quote(prompt: str) -> Callable[[], dict[str, Any]]:
        # Silent clips: the voiceover and the music bed are the sound. They also cost less.
        return lambda: treza(
            "make_video",
            {"prompt": prompt, "durationSec": opts.seconds, "aspectRatio": "9:16", "withAudio": False, "maxPriceUsd": opts.max_cost},
        )

    try:
        # 1. Price everything before spending anything. Quotes are free.
        balance = float(treza("get_credit_balance").get("balanceUsd") or 0)
        pipeline_id = script_pipeline_id()
        script_price = float(treza("estimate_run_cost", {"pipelineId": pipeline_id, "inputs": {"topic": topic}})["estimatedChargeUsd"])
        sample = clip_quote(f"{topic}, cinematic vertical shot")()
        clip_price = float(sample["estimatedChargeUsd"])
        model = sample["model"]["name"] if isinstance(sample.get("model"), dict) else sample.get("model")
        total = round(script_price + 3 * clip_price, 2)

        print(f"\nA Short about: {topic} ({3 * int(sample['durationSec'])} seconds)")
        print(f"  Script and voiceover                        ${script_price:.2f}")
        print(f"  3 clips, {sample['durationSec']}s each, {model}, no sound    3 x ${clip_price:.2f} = ${3 * clip_price:.2f}")
        print("  Assembly: music, captions, 1080x1920        free once your account has bought credits")
        print(f"  Total                                       about ${total:.2f}  (max cost ${opts.max_cost:.2f}, balance ${balance:.2f})\n")

        if total > opts.max_cost:
            print(f"That is over --max-cost ${opts.max_cost:.2f}. Nothing was spent.", file=sys.stderr)
            return 1
        if not opts.yes:
            print("Nothing was spent. Run it again with --yes to make it.")
            return 0
        if balance < total:
            print(f"Your balance (${balance:.2f}) does not cover about ${total:.2f}. Nothing was spent. Add credits at {TOP_UP_URL}", file=sys.stderr)
            return 1

        # 2. The script: one run writes the voiceover, reads it aloud and plans three shots.
        spent = 0.0
        quoted, run = start_quoted(lambda: treza("estimate_run_cost", {"pipelineId": pipeline_id, "inputs": {"topic": topic}}), opts.max_cost, {"topic": topic})
        spent += float(quoted["estimatedChargeUsd"])
        print("Writing and recording the voiceover...")
        outputs = wait_for(pipeline_id, run["runId"], "The script")["outputs"]
        print(f"  Voiceover: {outputs['script'].strip()}")
        shots = parse_shots(str(outputs.get("shots", "")), topic)

        # 3. Three clips, each quoted and started once, rendering side by side.
        clips = []
        for n, shot in enumerate(shots, 1):
            quoted, run = start_quoted(clip_quote(shot), opts.max_cost - spent)
            spent += float(quoted["estimatedChargeUsd"])
            clips.append((quoted["pipelineId"], run["runId"]))
            print(f"  Clip {n}: {shot}")
        print("Rendering the clips...")
        clip_urls = [wait_for(p, r, f"Clip {n}")["outputs"]["video"] for n, (p, r) in enumerate(clips, 1)]

        # 4. One Short: the clips in order over the voiceover, a composed music bed ducked under
        #    the voice, burned-in captions, 1080x1920. Free once the account has bought credits.
        print("Assembling the Short...")
        try:
            assembly = treza(
                "assemble_video",
                {
                    "clipUrls": clip_urls,
                    "narrationUrl": outputs["narration"],
                    "musicPrompt": opts.music,
                    "captions": True,
                    "orientation": "vertical",
                    "transition": "fade",
                    "audioFadeOutSec": 2,
                    "fadeOutSec": 1,
                    "name": f"Short: {topic}"[:200],
                },
            )
        except Refused as refusal:
            print(f"{refusal}\nThe clips are made and kept in your library:", *clip_urls, sep="\n  ", file=sys.stderr)
            return 1
        if assembly.get("warning"):
            print(f"  Note: {assembly['warning']}")
        cost = "free" if assembly.get("charged") is False else "charged, as this account has not bought credits yet"
        print(f"  {assembly.get('lengthSec', '?')} seconds, {cost}")
        final = wait_for(assembly["pipelineId"], assembly["runId"], "The assembly")
        url = final["outputs"]["video"]
        size = download(url, opts.out)
    except Refused as refusal:
        print(refusal, file=sys.stderr)
        return 1

    print(f"\nSaved {opts.out} ({size} bytes). Spent about ${spent:.2f}.")
    print(f"Link: {url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
