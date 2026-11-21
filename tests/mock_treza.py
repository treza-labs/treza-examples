"""A stand-in for Treza's API, so the recipes can be tested with no key and no credits.

It answers POST /api/v1/tools/<name> the way https://www.trezalabs.com does, with
the same field names and refusal codes, for the tools the recipes call:

    get_credit_balance, make_video, make_image, estimate_run_cost, run_pipeline,
    get_run, cancel_run, list_pipelines, create_pipeline, assemble_video

It also serves the "finished files" under /media/ and imitates the paid answer of
the x402 video endpoint (POST /api/x402/video, then its status URL).

Prices follow Treza's at the time of writing: Veo 3.1 Lite at about $0.07 a
second with sound and $0.042 without, a Nano Banana picture at $0.06 (free for
the first few each day). Every render "finishes" after one poll.

Run it on its own:

    python3 tests/mock_treza.py --port 8765
    TREZA_BASE_URL=http://127.0.0.1:8765 TREZA_API_KEY=treza_live_test ./curl/make-video.sh

The mock is stricter than Treza in one way: it refuses argument names it does not
know, so a typo in a recipe fails the tests instead of being ignored.
"""

from __future__ import annotations

import argparse
import json
import re
import struct
import threading
import time
import uuid
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

TOP_UP_URL = "https://www.trezalabs.com/platform/settings#billing"

VIDEO_MODEL = {"id": "google/veo-3.1-lite", "name": "Veo 3.1 Lite"}
VIDEO_TAKES = [4, 6, 8]
VIDEO_RATE = {True: 0.07, False: 0.042}  # USD a second, with and without sound
IMAGE_MODEL = {"id": "google/gemini-2.5-flash-image", "name": "Nano Banana (Gemini 2.5 Flash Image)"}
IMAGE_PRICE = 0.06
NODE_PRICES = {"ai-model": 0.042, "tts": 0.10, "text-input": 0.0, "output": 0.0}

# The ports and settings of the node types a recipe may wire (Treza's node registry).
NODE_TYPES = {
    "text-input": {"inputs": [], "outputs": ["out"], "config": ["value"]},
    "ai-model": {
        "inputs": ["prompt", "context", "media"],
        "outputs": ["completion"],
        "config": [
            "model", "systemPrompt", "temperature", "maxTokens", "reasoning", "maxRetries",
            "fallbackModel", "mediaFallbackModel", "avoidRecentRepeats", "recentWindow",
        ],
    },
    "tts": {
        "inputs": ["text", "voice"],
        "outputs": ["audio", "result"],
        "config": ["model", "customModel", "voice", "customVoice", "speed", "emotion", "pitch", "volume"],
    },
    "output": {"inputs": ["in"], "outputs": [], "config": ["name"]},
}

# The arguments each tool takes (Treza's MCP tool schemas).
TOOL_ARGS = {
    "get_credit_balance": set(),
    "make_video": {
        "prompt", "durationSec", "aspectRatio", "withAudio", "maxPriceUsd", "model", "name",
        "continueFromVideoUrl", "firstFrameUrl", "lastFrameUrl",
    },
    "make_image": {"prompt", "referenceImageUrls", "aspectRatio", "model", "maxPriceUsd", "name"},
    "estimate_run_cost": {"pipelineId", "inputs"},
    "run_pipeline": {"pipelineId", "inputs", "preview", "quoteId", "requestId", "callbackUrl"},
    "get_run": {"pipelineId", "runId"},
    "cancel_run": {"pipelineId", "runId"},
    "list_pipelines": set(),
    "create_pipeline": {"name", "description", "templateId", "nodes", "edges"},
    "assemble_video": {
        "clipUrls", "narrationUrl", "musicUrl", "musicPrompt", "audioFadeInSec", "audioFadeOutSec",
        "fadeInSec", "fadeOutSec", "captions", "orientation", "transition", "stillSeconds",
        "stillMotion", "name", "requestId", "callbackUrl",
    },
}
ORIENTATIONS = {"vertical", "horizontal", "match_first"}
TRANSITIONS = {"none", "fade", "fadeblack", "wipeleft", "zoomin"}

NARRATION = (
    "Octopuses taste with their arms. Each sucker holds thousands of chemical sensors, "
    "so a single touch tells them whether a rock hides a crab. Two thirds of their "
    "neurons live in those arms, which can explore on their own."
)
SHOTS = (
    "1. Macro shot of an octopus arm curling over a mossy rock, suckers gripping, soft blue light, slow push in\n"
    "2. An octopus slides its arm into a crevice and a small crab scuttles out, shallow reef, sunbeams\n"
    "3. Wide shot of an octopus gliding over the reef at dusk, arms trailing, camera drifting alongside"
)


def tiny_png() -> bytes:
    """A real 1x1 PNG, so a picture that comes back can be opened."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    pixels = zlib.compress(b"\x00\x2a\x6f\xd8")
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", pixels) + chunk(b"IEND", b"")


MEDIA = {
    ".mp4": ("video/mp4", b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2" + b"\x00" * 64),
    ".png": ("image/png", tiny_png()),
    ".mp3": ("audio/mpeg", b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\x00" * 64),
}


class Refusal(Exception):
    def __init__(self, status: int, error: str, code: str | None = None, **extra: Any):
        super().__init__(error)
        self.status = status
        self.body = {"error": error, **({"code": code} if code else {}), **extra}


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())


def new_id(prefix: str) -> str:
    return f"{prefix}{int(time.time() * 1000)}_{uuid.uuid4().hex[:9]}"


class MockTreza:
    """What the mock remembers: pipelines, quotes, runs, balance and every call."""

    def __init__(self, balance_usd: float = 20.0, free_images_left: int = 5, running_polls: int = 1, poll_after_sec: float = 2):
        self.lock = threading.Lock()
        self.base_url = ""
        self.balance = balance_usd
        self.free_images_left = free_images_left
        self.running_polls = running_polls
        self.poll_after_sec = poll_after_sec
        self.fail_runs = False
        self.stale_quotes = 0  # refuse this many starts with STALE_QUOTE, as when a pipeline changed after its quote
        self.pipelines: dict[str, dict] = {}
        self.quotes: dict[str, dict] = {}
        self.runs: dict[str, dict] = {}
        self.media: set[str] = set()
        self.calls: list[dict] = []
        self.x402_orders: dict[str, dict] = {}

    # ----------------------------------------------------------- helpers

    def media_url(self, name: str) -> str:
        url = f"{self.base_url}/media/{name}?sig={uuid.uuid4().hex[:16]}"
        self.media.add(url)
        return url

    def quote(self, pipeline_id: str, price: float, free: bool = False) -> dict:
        quote_id = "q_" + uuid.uuid4().hex[:12]
        self.quotes[quote_id] = {"pipelineId": pipeline_id, "price": price, "free": free}
        sufficient = free or self.balance >= price
        return {
            "pipelineId": pipeline_id,
            "pipelineName": self.pipelines[pipeline_id]["name"],
            "quoteId": quote_id,
            "quoteExpiresAt": int(time.time()) + 86400,
            "estimatedChargeUsd": 0 if free else price,
            **({"listChargeUsd": price} if free else {}),
            "lines": [{"label": self.pipelines[pipeline_id]["kind"], "chargeUsd": 0 if free else price}],
            "balanceUsd": round(self.balance, 2),
            "enforced": True,
            "sufficient": sufficient,
            **({} if sufficient else {"topUpUrl": TOP_UP_URL}),
        }

    def add_pipeline(self, kind: str, name: str, **extra: Any) -> str:
        pipeline_id = new_id("pipeline_")
        self.pipelines[pipeline_id] = {"id": pipeline_id, "kind": kind, "name": name, "updatedAt": now_iso(), **extra}
        return pipeline_id

    def start_run(self, pipeline_id: str, outputs: dict) -> dict:
        run_id = new_id("run_")
        self.runs[run_id] = {
            "pipelineId": pipeline_id,
            "startedAt": now_iso(),
            "started": time.time(),
            "pollsLeft": self.running_polls,
            "outputs": outputs,
            "fail": self.fail_runs,
        }
        return {"runId": run_id, "status": "running", "startedAt": self.runs[run_id]["startedAt"]}

    def outputs_for(self, pipeline: dict) -> dict:
        n = len(self.runs) + 1
        if pipeline["kind"] == "video":
            return {"video": self.media_url(f"clip-{n}.mp4")}
        if pipeline["kind"] == "image":
            return {"image": self.media_url(f"image-{n}.png")}
        if pipeline["kind"] == "assembly":
            return {"video": self.media_url(f"assembled-{n}.mp4")}
        # A pipeline the caller built: each Output node by its name.
        outputs = {}
        nodes = {node["id"]: node for node in pipeline.get("nodes", [])}
        for edge in pipeline.get("edges", []):
            target = nodes.get(edge["target"], {})
            if target.get("type") != "output":
                continue
            name = (target.get("config") or {}).get("name") or target["id"]
            source = nodes.get(edge["source"], {})
            if source.get("type") == "tts":
                outputs[name] = self.media_url(f"narration-{n}.mp3")
            elif source.get("type") == "ai-model":
                system = str((source.get("config") or {}).get("systemPrompt", "")).lower()
                outputs[name] = SHOTS if "shot" in system else NARRATION
            else:
                outputs[name] = "ok"
        return outputs

    # ------------------------------------------------------------- tools

    def call(self, tool: str, args: dict) -> dict:
        if tool not in TOOL_ARGS:
            raise Refusal(404, f'There is no tool named "{tool}".', "UNKNOWN_TOOL", tools=sorted(TOOL_ARGS))
        unknown = set(args) - TOOL_ARGS[tool]
        if unknown:
            raise Refusal(400, f"{tool} does not take {', '.join(sorted(unknown))} (the mock refuses unknown arguments).", "INVALID_REQUEST")
        return getattr(self, f"tool_{tool}")(args)

    def tool_get_credit_balance(self, args: dict) -> dict:
        return {
            "balanceUsd": round(self.balance, 2),
            "enforced": True,
            "approxVideosRemaining": int(self.balance // 0.56),
            "topUpUrl": TOP_UP_URL,
        }

    def tool_make_video(self, args: dict) -> dict:
        prompt = str(args.get("prompt") or "").strip()
        if not prompt:
            raise Refusal(400, "Describe the video in prompt. Nothing was created or charged.", "NO_PROMPT")
        aspect = args.get("aspectRatio", "16:9")
        if aspect not in ("16:9", "9:16", "1:1"):
            raise Refusal(400, f'aspectRatio must be "16:9", "9:16" or "1:1", not {json.dumps(aspect)}.', "INVALID_REQUEST")
        model = args.get("model")
        if model not in (None, VIDEO_MODEL["id"]):
            raise Refusal(400, f'"{model}" is not a video model that renders {aspect} here. Ones that do: {VIDEO_MODEL["id"]}. Nothing was created or charged.', "UNKNOWN_MODEL")
        asked = float(args.get("durationSec", 4))
        takes = [t for t in VIDEO_TAKES if t >= asked and t - asked <= 2]
        if not takes:
            raise Refusal(400, f"No video model here renders {asked:g}s in one clip; the longest is 8s. Nothing was created or charged.", "TOO_LONG")
        seconds = takes[0]
        with_audio = args.get("withAudio") is not False
        price = round(VIDEO_RATE[with_audio] * seconds, 2)
        cap = args.get("maxPriceUsd")
        if cap is not None and price > float(cap):
            raise Refusal(
                400,
                f"This video costs ${price:.2f} on Veo 3.1 Lite at {seconds}s, over the ${float(cap):.2f} limit. Nothing was created or charged.",
                "OVER_BUDGET",
                estimatedChargeUsd=price,
                model=VIDEO_MODEL["id"],
                durationSec=seconds,
            )
        pipeline_id = self.add_pipeline("video", args.get("name") or f"Video: {prompt[:40]}", prompt=prompt)
        answer = self.quote(pipeline_id, price)
        answer.update(
            {
                "model": VIDEO_MODEL,
                "durationSec": seconds,
                **({"requestedDurationSec": asked} if seconds != asked else {}),
                "aspectRatio": aspect,
                "withAudio": with_audio,
                "note": "Nothing is rendering yet. Once they accept, call run_pipeline with this pipelineId and quoteId.",
            }
        )
        return answer

    def tool_make_image(self, args: dict) -> dict:
        prompt = str(args.get("prompt") or "").strip()
        if not prompt:
            raise Refusal(400, "Describe the picture in prompt. Nothing was created or charged.", "NO_PROMPT")
        free = self.free_images_left > 0 and args.get("model") in (None, IMAGE_MODEL["id"])
        cap = args.get("maxPriceUsd")
        if not free and cap is not None and IMAGE_PRICE > float(cap):
            raise Refusal(
                400,
                f"This image costs ${IMAGE_PRICE:.2f} on Nano Banana, over the ${float(cap):.2f} limit. Nothing was created or charged.",
                "OVER_BUDGET",
                estimatedChargeUsd=IMAGE_PRICE,
                model=IMAGE_MODEL["id"],
            )
        pipeline_id = self.add_pipeline("image", f"Image: {prompt[:40]}", prompt=prompt)
        answer = self.quote(pipeline_id, IMAGE_PRICE, free=free)
        answer["model"] = IMAGE_MODEL
        if args.get("aspectRatio"):
            answer["aspectRatio"] = args["aspectRatio"]
        if free:
            answer.update({"freeImage": True, "freeImagesLeftToday": self.free_images_left})
        return answer

    def tool_list_pipelines(self, args: dict) -> dict:
        built = [p for p in self.pipelines.values() if p["kind"] == "built"]
        return {
            "pipelines": [
                {"id": p["id"], "name": p["name"], "status": "draft", "updatedAt": p["updatedAt"], "nodeCount": len(p["nodes"])}
                for p in built
            ]
        }

    def tool_create_pipeline(self, args: dict) -> dict:
        nodes, edges = args.get("nodes"), args.get("edges")
        if not isinstance(nodes, list) or not isinstance(edges, list):
            raise Refusal(400, "Pass nodes and edges together (edges may be []): a graph is replaced whole.")
        issues = []
        by_id = {}
        for node in nodes:
            kind = NODE_TYPES.get(node.get("type"))
            if not kind:
                issues.append(f'Node "{node.get("id")}" has an unknown type "{node.get("type")}".')
                continue
            by_id[node["id"]] = node
            for key in node.get("config") or {}:
                if key not in kind["config"]:
                    issues.append(f'Node "{node["id"]}" ({node["type"]}): "{key}" is not a setting of this node.')
        for i, edge in enumerate(edges):
            extra = set(edge) - {"id", "source", "sourceHandle", "target", "targetHandle"}
            if extra:
                issues.append(f"edges[{i}]: unknown keys {sorted(extra)}.")
            source, target = by_id.get(edge.get("source")), by_id.get(edge.get("target"))
            if not source or not target:
                issues.append(f"edges[{i}]: no node has the id {edge.get('source')!r} or {edge.get('target')!r}.")
                continue
            if edge.get("sourceHandle") not in NODE_TYPES[source["type"]]["outputs"]:
                issues.append(f'edges[{i}]: "{edge.get("sourceHandle")}" is not an output of "{source["id"]}" ({source["type"]}).')
            if edge.get("targetHandle") not in NODE_TYPES[target["type"]]["inputs"]:
                issues.append(f'edges[{i}]: "{edge.get("targetHandle")}" is not an input of "{target["id"]}" ({target["type"]}).')
        if issues:
            raise Refusal(400, "Pipeline validation failed, so nothing was saved: " + " ".join(issues))
        pipeline_id = self.add_pipeline("built", args.get("name", "Untitled"), nodes=nodes, edges=edges)
        return {"id": pipeline_id, "name": args.get("name"), "status": "draft", "issues": [], "note": "Draft created."}

    def built_pipeline(self, pipeline_id: Any) -> dict:
        pipeline = self.pipelines.get(pipeline_id)
        if not pipeline:
            raise Refusal(404, "Pipeline not found or access denied.")
        return pipeline

    def check_inputs(self, pipeline: dict, inputs: Any, what: str) -> None:
        if pipeline["kind"] != "built":
            if inputs:
                raise Refusal(400, f"This pipeline has no input steps to take inputs. {what}")
            return
        entries = {n["id"]: n for n in pipeline["nodes"] if n["type"] == "text-input"}
        given = inputs or {}
        if not isinstance(given, dict):
            raise Refusal(400, f"inputs must be an object keyed by entry node id. {what}")
        for key in given:
            if key not in entries:
                raise Refusal(400, f'"{key}" names no entry node. Entry nodes: {", ".join(entries)}. {what}')
        for node_id, node in entries.items():
            if not str(given.get(node_id) or (node.get("config") or {}).get("value") or "").strip():
                raise Refusal(400, f'Entry node "{node_id}" has nothing saved and no input. {what}')

    def tool_estimate_run_cost(self, args: dict) -> dict:
        pipeline = self.built_pipeline(args.get("pipelineId"))
        self.check_inputs(pipeline, args.get("inputs"), "Nothing was priced.")
        if pipeline["kind"] == "built":
            price = round(sum(NODE_PRICES.get(n["type"], 0) for n in pipeline["nodes"]), 2)
        else:
            price = pipeline.get("price", 0.28)
        return self.quote(pipeline["id"], price)

    def tool_run_pipeline(self, args: dict) -> dict:
        pipeline = self.built_pipeline(args.get("pipelineId"))
        quote_id = args.get("quoteId")
        quote = None
        if quote_id is not None:
            quote = self.quotes.get(quote_id)
            if not quote:
                raise Refusal(400, f"quoteId {json.dumps(quote_id)} is not a current quote for this account. Nothing was run or charged.", "UNKNOWN_QUOTE")
            if quote["pipelineId"] != pipeline["id"]:
                raise Refusal(400, f"quoteId {quote_id} was quoted for pipeline {quote['pipelineId']}, not {pipeline['id']}. Nothing was run or charged.", "QUOTE_MISMATCH")
            if quote.get("used"):
                return {**quote["used"], "repeat": True}
            if self.stale_quotes > 0:
                self.stale_quotes -= 1
                raise Refusal(
                    400,
                    f"The pipeline changed after quote {quote_id} priced it at ${quote['price']:.2f}, so that price no longer describes this run. Nothing was run or charged.",
                    "STALE_QUOTE",
                    quotedChargeUsd=quote["price"],
                )
        elif not args.get("requestId"):
            pass  # Treza starts it, without the protection a quote or requestId gives a retry.
        self.check_inputs(pipeline, args.get("inputs"), "No run was started and nothing was charged.")
        free = bool(quote and quote["free"])
        price = 0 if free else (quote["price"] if quote else 0.28)
        if price > self.balance:
            raise Refusal(402, f"This run costs ${price:.2f} and the balance is ${self.balance:.2f}. Nothing was charged.", "INSUFFICIENT_CREDITS", topUpUrl=TOP_UP_URL)
        self.balance -= price
        if free:
            self.free_images_left -= 1
        started = self.start_run(pipeline["id"], self.outputs_for(pipeline))
        started["note"] = "Started. Poll get_run with this runId."
        if free:
            started["charged"] = False
        if quote is not None:
            quote["used"] = started
        return started

    def tool_get_run(self, args: dict) -> dict:
        self.built_pipeline(args.get("pipelineId"))
        run = self.runs.get(args.get("runId"))
        if not run or run["pipelineId"] != args.get("pipelineId"):
            raise Refusal(400, "Run not found.")
        base = {"runId": args["runId"], "pipelineId": run["pipelineId"], "status": "running", "trigger": "api", "startedAt": run["startedAt"]}
        if run.get("cancelled"):
            return {**base, "status": "cancelled", "finishedAt": now_iso(), "durationMs": 1000, "nodes": []}
        if run["pollsLeft"] > 0:
            run["pollsLeft"] -= 1
            return {**base, "progress": {"done": 1, "total": 3, "now": "Video"}, "pollAfterSec": self.poll_after_sec, "nodes": []}
        finished = {**base, "finishedAt": now_iso(), "durationMs": int((time.time() - run["started"]) * 1000) + 41000}
        if run["fail"]:
            return {
                **finished,
                "status": "error",
                "statusNote": "The video model refused the prompt.",
                "nodes": [{"nodeId": "video", "type": "video-gen", "label": "Video", "status": "error", "error": "Refused by the provider."}],
            }
        return {**finished, "status": "success", "outputs": run["outputs"], "note": "Finished.", "nodes": []}

    def tool_cancel_run(self, args: dict) -> dict:
        run = self.runs.get(args.get("runId"))
        if run:
            run["cancelled"] = True
        return {"runId": args.get("runId"), "pipelineId": args.get("pipelineId"), "status": "cancelling", "note": "It stops once the step running now finishes."}

    def tool_assemble_video(self, args: dict) -> dict:
        clips = args.get("clipUrls")
        if not isinstance(clips, list) or not clips:
            raise Refusal(400, "Pass two or more clipUrls, or one clip with a narrationUrl, a musicUrl or a musicPrompt to lay under it.")
        for url in [*clips, *(u for u in [args.get("narrationUrl"), args.get("musicUrl")] if u)]:
            if url not in self.media:
                raise Refusal(400, f"{url} is not in this account's library or a run's outputs. Nothing was assembled.")
        if args.get("musicUrl") and args.get("musicPrompt"):
            raise Refusal(400, "Pass musicUrl for a track from list_assets, or musicPrompt to have one composed for this cut, not both.")
        if args.get("orientation", "match_first") not in ORIENTATIONS:
            raise Refusal(400, f"orientation must be one of {sorted(ORIENTATIONS)}.", "INVALID_REQUEST")
        if args.get("transition", "none") not in TRANSITIONS:
            raise Refusal(400, f"transition must be one of {sorted(TRANSITIONS)}.", "INVALID_REQUEST")
        pipeline_id = self.add_pipeline("assembly", args.get("name") or "Stitched video")
        started = self.start_run(pipeline_id, self.outputs_for(self.pipelines[pipeline_id]))
        return {
            **started,
            "pipelineId": pipeline_id,
            "charged": False,
            "clips": [{"url": u, "kind": "video", "durationSec": 6} for u in clips],
            **({"captions": True} if args.get("captions") else {}),
            **({"composedMusic": {"model": "google/lyria-3"}} if args.get("musicPrompt") else {}),
            "lengthSec": 6 * len(clips),
            "note": "Rendering. Poll get_run with this pipelineId and runId.",
        }

    # ----------------------------------------------------------------- x402

    def x402_buy(self, body: dict) -> dict:
        order_id = uuid.uuid4().hex[:12]
        status_url = f"{self.base_url}/api/x402/status/{order_id}?ticket={uuid.uuid4().hex}"
        self.x402_orders[order_id] = {"polls": self.running_polls, "video": self.media_url(f"x402-{order_id}.mp4")}
        return {
            "status": "running",
            "runId": "run_" + order_id,
            "statusUrl": status_url,
            "pollAfterMs": 200,
            "paidUsd": 0.42,
            "network": "eip155:8453",
            "transaction": "0x" + "0" * 64,
            "seconds": body.get("seconds", 5),
            "model": body.get("model", "minimax-h3"),
        }

    def x402_status(self, order_id: str) -> dict:
        order = self.x402_orders.get(order_id)
        if not order:
            return {"status": "error", "message": "Unknown order."}
        if order["polls"] > 0:
            order["polls"] -= 1
            return {"status": "running", "pollAfterMs": 200}
        return {"status": "success", "video": order["video"]}


def make_handler(mock: MockTreza):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # quiet
            pass

        def send_json(self, status: int, body: Any, headers: dict | None = None) -> None:
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(data)

        def read_body(self) -> Any:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length).decode() if length else ""
            if not raw.strip():
                return {}
            try:
                return json.loads(raw)
            except ValueError:
                return None

        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/_calls":
                with mock.lock:
                    return self.send_json(200, mock.calls)
            match = re.fullmatch(r"/api/x402/status/(\w+)", path)
            if match:
                with mock.lock:
                    return self.send_json(200, mock.x402_status(match.group(1)))
            if path.startswith("/media/"):
                if self.headers.get("Authorization"):
                    # Finished files are public links. A client should not send its key to them.
                    return self.send_json(400, {"error": "Media links take no Authorization header."})
                kind = MEDIA.get(path[path.rfind("."):])
                if not kind:
                    return self.send_json(404, {"error": "Not found."})
                self.send_response(200)
                self.send_header("Content-Type", kind[0])
                self.send_header("Content-Length", str(len(kind[1])))
                self.end_headers()
                self.wfile.write(kind[1])
                return
            self.send_json(404, {"error": "Not found."})

        def do_POST(self):
            path = urlparse(self.path).path
            body = self.read_body()
            if path == "/api/x402/video":
                with mock.lock:
                    mock.calls.append({"tool": "x402/video", "args": body})
                    order = mock.x402_buy(body or {})
                return self.send_json(200, order, {"X-Status-Url": order["statusUrl"]})
            match = re.fullmatch(r"/api/v1/tools/([a-z_]+)", path)
            if not match:
                return self.send_json(404, {"error": "Not found."})
            tool = match.group(1)
            auth = self.headers.get("Authorization", "")
            if not auth.startswith("Bearer treza_live_"):
                return self.send_json(
                    401,
                    {
                        "error": 'Send a Treza API key as "Authorization: Bearer treza_live_...". Keys are made in the Treza dashboard under API keys and need a pipelines permission.',
                        "code": "UNAUTHORIZED",
                    },
                )
            if not isinstance(body, dict):
                return self.send_json(400, {"error": "The body must be a JSON object: the tool's arguments.", "code": "INVALID_BODY"})
            with mock.lock:
                mock.calls.append({"tool": tool, "args": body, "userAgent": self.headers.get("User-Agent", "")})
                try:
                    answer = mock.call(tool, body)
                except Refusal as refusal:
                    return self.send_json(refusal.status, refusal.body)
            self.send_json(200, answer)

    return Handler


def serve(mock: MockTreza, port: int = 0, host: str = "127.0.0.1") -> ThreadingHTTPServer:
    """Start the mock in a background thread and return the server (its port is server.server_port)."""
    server = ThreadingHTTPServer((host, port), make_handler(mock))
    mock.base_url = f"http://{host}:{server.server_port}"
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a stand-in for Treza's API on this machine.")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--balance", type=float, default=20.0, help="the account's balance in USD")
    parser.add_argument("--free-images", type=int, default=5, help="free images left today")
    args = parser.parse_args()
    mock = MockTreza(balance_usd=args.balance, free_images_left=args.free_images)
    server = serve(mock, args.port)
    print(f"Mock Treza API at {mock.base_url}", flush=True)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
