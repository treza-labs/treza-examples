"""Run every recipe against the mock Treza API (tests/mock_treza.py). No key, no credits.

    python3 tests/run_tests.py            # all of them
    python3 tests/run_tests.py -k shorts  # some of them

Needs: bash, curl and jq for curl/; `requests` for python/ and shorts-from-a-prompt/;
Node 23.6+ (or tsx on PATH) for typescript/; nbformat, IPython and langchain-treza for the
notebook (plus langchain for its agent cells). Tests whose tools are missing are skipped.

Optional, to check the workflows against the real node definitions:
    N8N_NODES_TREZA_DIR=<a built checkout of treza-labs/n8n-nodes-treza>
    TREZA_COMFYUI_DIR=<a checkout of treza-labs/treza-comfyui>
    X402_NODE_MODULES=<node_modules with @x402/fetch, @x402/evm, viem and tsx>, to run x402/buy-video.ts
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from mock_treza import MockTreza, serve  # noqa: E402

PNG = b"\x89PNG"
MP4 = b"ftyp"


def has_module(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def node_version() -> tuple[int, int]:
    node = shutil.which("node")
    if not node:
        return (0, 0)
    found = re.match(r"v(\d+)\.(\d+)", subprocess.run([node, "--version"], capture_output=True, text=True).stdout)
    return (int(found.group(1)), int(found.group(2))) if found else (0, 0)


class Recipe(unittest.TestCase):
    """Each test gets its own mock Treza and its own empty folder."""

    def setUp(self):
        self.mock = MockTreza()
        self.server = serve(self.mock)
        self.dir = Path(tempfile.mkdtemp(prefix="treza-examples-"))
        self.env = {**os.environ, "TREZA_BASE_URL": self.mock.base_url, "TREZA_API_KEY": "treza_live_test"}

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def run_recipe(self, *cmd: str, env: dict | None = None, timeout: int = 120) -> subprocess.CompletedProcess:
        return subprocess.run(list(cmd), cwd=self.dir, env={**self.env, **(env or {})}, capture_output=True, text=True, timeout=timeout)

    def asked(self, tool: str) -> list[dict]:
        return [c["args"] for c in self.mock.calls if c["tool"] == tool]

    def assert_file(self, name: str, magic: bytes):
        path = self.dir / name
        self.assertTrue(path.exists(), f"{name} was not saved")
        self.assertIn(magic, path.read_bytes()[:16])

    def assert_quoted_then_started_once(self, quote_tool: str):
        """The flow every recipe follows: a quote, then one start with that quote's id, then polls."""
        quotes = [c for c in self.mock.calls if c["tool"] == quote_tool]
        starts = self.asked("run_pipeline")
        self.assertEqual(len(starts), 1, "started more than once")
        self.assertTrue(quotes, "never quoted")
        self.assertIn(starts[0]["quoteId"], self.mock.quotes)
        self.assertGreaterEqual(len(self.asked("get_run")), 1)
        tools = [c["tool"] for c in self.mock.calls]
        self.assertLess(tools.index(quote_tool), tools.index("run_pipeline"))


# --------------------------------------------------------------------- curl


@unittest.skipUnless(shutil.which("bash") and shutil.which("curl") and shutil.which("jq"), "needs bash, curl and jq")
class CurlRecipe(Recipe):
    def test_video_is_quoted_started_once_and_downloaded(self):
        out = self.run_recipe("bash", str(ROOT / "curl/make-video.sh"), "a fox in snow")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assert_file("video.mp4", MP4)
        self.assert_quoted_then_started_once("make_video")
        self.assertEqual(self.asked("make_video")[0], {"prompt": "a fox in snow", "durationSec": 5, "aspectRatio": "9:16", "maxPriceUsd": 1})
        self.assertIn("6s 9:16 on Veo 3.1 Lite for $0.42", out.stdout)

    def test_over_max_cost_starts_nothing(self):
        out = self.run_recipe("bash", str(ROOT / "curl/make-video.sh"), env={"MAX_COST": "0.30"})
        self.assertEqual(out.returncode, 1)
        self.assertIn("over the $0.30 limit", out.stderr)
        self.assertEqual(self.asked("run_pipeline"), [])

    def test_low_balance_starts_nothing(self):
        self.mock.balance = 0.10
        out = self.run_recipe("bash", str(ROOT / "curl/make-video.sh"))
        self.assertEqual(out.returncode, 1)
        self.assertIn("Add credits at", out.stderr)
        self.assertEqual(self.asked("run_pipeline"), [])

    def test_a_broken_render_says_why(self):
        self.mock.fail_runs = True
        out = self.run_recipe("bash", str(ROOT / "curl/make-video.sh"))
        self.assertEqual(out.returncode, 1)
        self.assertIn("The video model refused the prompt.", out.stderr)

    def test_free_image(self):
        out = self.run_recipe("bash", str(ROOT / "curl/free-image.sh"), "a lighthouse")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assert_file("image.png", PNG)
        self.assert_quoted_then_started_once("make_image")
        self.assertNotIn("maxPriceUsd", self.asked("make_image")[0])
        self.assertAlmostEqual(self.mock.balance, 20.0)  # nothing was charged

    def test_no_free_image_left_spends_nothing(self):
        self.mock.free_images_left = 0
        out = self.run_recipe("bash", str(ROOT / "curl/free-image.sh"))
        self.assertEqual(out.returncode, 1)
        self.assertIn("free pictures are used up", out.stderr)
        self.assertEqual(self.asked("run_pipeline"), [])

    def test_paying_for_an_image_when_allowed(self):
        self.mock.free_images_left = 0
        out = self.run_recipe("bash", str(ROOT / "curl/free-image.sh"), env={"MAX_COST": "0.10"})
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(self.asked("make_image")[0]["maxPriceUsd"], 0.1)
        self.assertAlmostEqual(self.mock.balance, 19.94)


# ------------------------------------------------------------------- python


@unittest.skipUnless(has_module("requests"), "needs requests")
class PythonRecipe(Recipe):
    def test_video(self):
        out = self.run_recipe(sys.executable, str(ROOT / "python/make_video.py"), "a fox in snow")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assert_file("video.mp4", MP4)
        self.assert_quoted_then_started_once("make_video")
        self.assertEqual(self.asked("make_video")[0]["maxPriceUsd"], 1.0)
        self.assertTrue(self.mock.calls[0]["userAgent"].startswith("treza-examples-python/"))

    def test_a_stale_quote_is_quoted_again(self):
        self.mock.stale_quotes = 1
        out = self.run_recipe(sys.executable, str(ROOT / "python/make_video.py"))
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(len(self.asked("make_video")), 2)
        self.assertEqual(len(self.asked("run_pipeline")), 2)
        self.assertAlmostEqual(self.mock.balance, 20.0 - 0.42)  # paid once

    def test_over_max_cost_starts_nothing(self):
        out = self.run_recipe(sys.executable, str(ROOT / "python/make_video.py"), "--max-cost", "0.2")
        self.assertEqual(out.returncode, 1)
        self.assertIn("Nothing was created or charged", out.stderr)
        self.assertEqual(self.asked("run_pipeline"), [])

    def test_bad_key(self):
        out = self.run_recipe(sys.executable, str(ROOT / "python/make_video.py"), env={"TREZA_API_KEY": "nope"})
        self.assertEqual(out.returncode, 1)
        self.assertIn("Send a Treza API key", out.stderr)


# --------------------------------------------------------------- typescript


def typescript_runner() -> list[str] | None:
    if node_version() >= (23, 6):  # Node 23.6+ runs .ts files as they are
        return [shutil.which("node")]
    tsx = shutil.which("tsx") or str(ROOT / "typescript/node_modules/.bin/tsx")
    return [tsx] if Path(tsx).exists() else None


@unittest.skipUnless(typescript_runner(), "needs Node 23.6+ or tsx")
class TypeScriptRecipe(Recipe):
    def test_video(self):
        out = self.run_recipe(*typescript_runner(), str(ROOT / "typescript/make-video.ts"), "a fox in snow", "--no-audio")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assert_file("video.mp4", MP4)
        self.assert_quoted_then_started_once("make_video")
        self.assertEqual(self.asked("make_video")[0]["withAudio"], False)
        self.assertIn("for $0.25", out.stdout)

    def test_a_stale_quote_is_quoted_again(self):
        self.mock.stale_quotes = 1
        out = self.run_recipe(*typescript_runner(), str(ROOT / "typescript/make-video.ts"))
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(len(self.asked("make_video")), 2)

    def test_over_max_cost_starts_nothing(self):
        out = self.run_recipe(*typescript_runner(), str(ROOT / "typescript/make-video.ts"), "--max-cost", "0.2")
        self.assertEqual(out.returncode, 1)
        self.assertEqual(self.asked("run_pipeline"), [])


# ------------------------------------------------------------------- shorts


@unittest.skipUnless(has_module("requests"), "needs requests")
class ShortsRecipe(Recipe):
    script = str(ROOT / "shorts-from-a-prompt/make_short.py")

    def test_without_yes_it_only_quotes(self):
        out = self.run_recipe(sys.executable, self.script, "how octopuses taste")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("about $0.93", out.stdout)
        self.assertIn("Nothing was spent", out.stdout)
        self.assertEqual(self.asked("run_pipeline"), [])
        self.assertEqual(self.asked("assemble_video"), [])
        # The script pipeline was saved once and is found by name the next time.
        self.run_recipe(sys.executable, self.script, "how octopuses taste")
        self.assertEqual(len(self.asked("create_pipeline")), 1)

    def test_with_yes_it_makes_the_short(self):
        out = self.run_recipe(sys.executable, self.script, "how octopuses taste", "--yes")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assert_file("short.mp4", MP4)
        starts = self.asked("run_pipeline")
        self.assertEqual(len(starts), 4)  # the script and three clips, each once
        self.assertEqual(starts[0]["inputs"], {"topic": "how octopuses taste"})
        self.assertTrue(all("quoteId" in s for s in starts))
        clips = self.asked("make_video")[1:]
        self.assertEqual(len(clips), 3)
        self.assertTrue(all(c["aspectRatio"] == "9:16" and c["withAudio"] is False for c in clips))
        self.assertTrue(all(not re.match(r"^\s*\d", c["prompt"]) for c in clips), "numbering left in the shot prompts")
        [assembly] = self.asked("assemble_video")
        self.assertEqual(len(assembly["clipUrls"]), 3)
        self.assertIn("narration-", assembly["narrationUrl"])
        self.assertTrue(assembly["captions"])
        self.assertEqual(assembly["orientation"], "vertical")
        self.assertIn("musicPrompt", assembly)
        self.assertAlmostEqual(self.mock.balance, 20.0 - 0.93, places=2)

    def test_over_max_cost_spends_nothing(self):
        out = self.run_recipe(sys.executable, self.script, "how octopuses taste", "--yes", "--max-cost", "0.50")
        self.assertEqual(out.returncode, 1)
        self.assertIn("over --max-cost", out.stderr)
        self.assertEqual(self.asked("run_pipeline"), [])

    def test_low_balance_spends_nothing(self):
        self.mock.balance = 0.50
        out = self.run_recipe(sys.executable, self.script, "how octopuses taste", "--yes")
        self.assertEqual(out.returncode, 1)
        self.assertIn("does not cover", out.stderr)
        self.assertEqual(self.asked("run_pipeline"), [])


# ----------------------------------------------------------------- notebook


NOTEBOOK = ROOT / "langchain-colab/treza_langchain_agent.ipynb"


def cells(tag: str) -> list[str]:
    import nbformat

    nb = nbformat.read(NOTEBOOK, as_version=4)
    return [c.source for c in nb.cells if c.cell_type == "code" and tag in c.metadata.get("tags", [])]


@unittest.skipUnless(has_module("nbformat"), "needs nbformat")
class NotebookFile(unittest.TestCase):
    def test_it_is_a_valid_notebook_with_a_colab_badge(self):
        import nbformat

        nb = nbformat.read(NOTEBOOK, as_version=4)
        nbformat.validate(nb)
        self.assertIn("colab.research.google.com/github/treza-labs/treza-examples/blob/main/langchain-colab/treza_langchain_agent.ipynb", nb.cells[0].source)
        for cell in nb.cells:
            if cell.cell_type == "code":
                self.assertEqual(cell.outputs, [], "outputs saved in the notebook")
                source = "\n".join(line for line in cell.source.splitlines() if not line.lstrip().startswith(("%", "!")))
                compile(source, "<cell>", "exec")


@unittest.skipUnless(all(has_module(m) for m in ("nbformat", "IPython", "langchain_treza")), "needs nbformat, IPython and langchain-treza")
class NotebookCells(Recipe):
    def run_cells(self, *tags: str, model=None) -> dict:
        saved = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(saved)))
        os.environ.update({"TREZA_BASE_URL": self.mock.base_url, "TREZA_API_KEY": "treza_live_test", "ANTHROPIC_API_KEY": "sk-ant-test"})
        namespace: dict = {"_scripted_model": model}
        for tag in tags:
            for source in cells(tag):
                exec(compile(source.replace('"anthropic:claude-sonnet-5-5"', "_scripted_model"), f"<{tag}>", "exec"), namespace)
        return namespace

    def test_direct_cells_check_the_balance_and_make_a_free_picture(self):
        ns = self.run_cells("key", "direct")
        self.assertEqual(len(self.asked("get_credit_balance")), 1)
        self.assertEqual(self.asked("make_image")[0]["maxPriceUsd"], 0.01)
        self.assertEqual(len(self.asked("run_pipeline")), 1)
        self.assertEqual(ns["image"]["price_usd"], 0)
        self.assertAlmostEqual(self.mock.balance, 20.0)

    def test_direct_cells_spend_nothing_once_the_free_pictures_are_used_up(self):
        self.mock.free_images_left = 0
        ns = self.run_cells("key", "direct")
        self.assertIn("over the Max cost of $0.01", ns["answer"])
        self.assertEqual(self.asked("run_pipeline"), [])

    @unittest.skipUnless(has_module("langchain"), "needs langchain")
    def test_agent_cells_make_a_capped_video(self):
        ns = self.run_cells("key", "agent", model=scripted_model())
        self.assertEqual(self.asked("make_video")[0]["maxPriceUsd"], 0.5)
        self.assertEqual(len(self.asked("run_pipeline")), 1)
        self.assertTrue(ns["clip"]["url"].startswith(self.mock.base_url))


def scripted_model():
    """A chat model that asks for one video, then answers: the agent cells without a real model."""
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.messages import AIMessage
    from langchain_core.outputs import ChatGeneration, ChatResult

    class Scripted(BaseChatModel):
        @property
        def _llm_type(self) -> str:
            return "scripted"

        def bind_tools(self, tools, **kwargs):
            return self

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            if any(m.type == "tool" for m in messages):
                message = AIMessage(content="Your hummingbird clip is ready.")
            else:
                call = {"name": "treza_generate_video", "args": {"prompt": "a hummingbird at a red flower", "aspect_ratio": "9:16", "duration_sec": 4}, "id": "call_1"}
                message = AIMessage(content="", tool_calls=[call])
            return ChatResult(generations=[ChatGeneration(message=message)])

    return Scripted()


# ---------------------------------------------------------------- workflows


class Workflows(unittest.TestCase):
    N8N = ROOT / "n8n/daily-vertical-video.json"
    COMFY = ROOT / "comfyui/treza_free_picture_to_vertical_clip.json"

    def test_n8n_workflow(self):
        wf = json.loads(self.N8N.read_text())
        names = {n["name"] for n in wf["nodes"]}
        self.assertEqual(len(names), len(wf["nodes"]))
        [treza] = [n for n in wf["nodes"] if n["type"].startswith("@treza/")]
        self.assertEqual(treza["type"], "@treza/n8n-nodes-treza.treza")
        self.assertIn(treza["typeVersion"], (1, 1.1))
        params = treza["parameters"]
        self.assertEqual((params["resource"], params["operation"]), ("video", "generate"))
        self.assertGreater(params["maxCostUsd"], 0)
        self.assertNotIn("credentials", treza)  # the person picks their own after import
        for source, out in wf["connections"].items():
            self.assertIn(source, names)
            for branch in out["main"]:
                for link in branch:
                    self.assertIn(link["node"], names)
        self.assertIn("n8n-nodes-base.scheduleTrigger", {n["type"] for n in wf["nodes"]})

    def test_comfyui_workflow(self):
        wf = json.loads(self.COMFY.read_text())
        types = {n["type"] for n in wf["nodes"]}
        self.assertTrue({"TrezaGenerateImage", "TrezaGenerateVideo"} <= types)
        image = next(n for n in wf["nodes"] if n["type"] == "TrezaGenerateImage")
        video = next(n for n in wf["nodes"] if n["type"] == "TrezaGenerateVideo")
        self.assertEqual(image["widgets_values_named"]["max_cost_usd"], 0.01)
        self.assertGreater(video["widgets_values_named"]["max_cost_usd"], 0)
        first_frame = next(i for i in video["inputs"] if i["name"] == "first_frame")
        link = next(l for l in wf["links"] if l[0] == first_frame["link"])
        self.assertEqual((link[1], link[5]), (image["id"], "IMAGE"))

    @unittest.skipUnless(os.environ.get("N8N_NODES_TREZA_DIR") and shutil.which("node"), "set N8N_NODES_TREZA_DIR to check against the real node")
    def test_n8n_workflow_against_the_real_node(self):
        out = subprocess.run(["node", str(ROOT / "tests/check_n8n.cjs"), os.environ["N8N_NODES_TREZA_DIR"], str(self.N8N)], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)

    @unittest.skipUnless(os.environ.get("TREZA_COMFYUI_DIR") and has_module("requests"), "set TREZA_COMFYUI_DIR to check against the real nodes")
    def test_comfyui_workflow_against_the_real_nodes(self):
        out = subprocess.run(
            [sys.executable, str(ROOT / "tests/check_comfyui.py"), os.environ["TREZA_COMFYUI_DIR"], str(self.COMFY)],
            capture_output=True, text=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)


# --------------------------------------------------------------------- x402


@unittest.skipUnless(os.environ.get("X402_NODE_MODULES"), "set X402_NODE_MODULES to run the x402 snippet")
class X402Snippet(Recipe):
    def test_buys_and_downloads(self):
        modules = Path(os.environ["X402_NODE_MODULES"])
        shutil.copy(ROOT / "x402/buy-video.ts", self.dir / "buy-video.ts")
        (self.dir / "node_modules").symlink_to(modules)
        (self.dir / "package.json").write_text('{"type": "module"}')
        # A throwaway key: the mock answers without a 402, so nothing is signed or paid.
        env = {"PRIVATE_KEY": "0x" + secrets.token_hex(32), "X402_VIDEO_ENDPOINT": f"{self.mock.base_url}/api/x402/video"}
        out = self.run_recipe(str(modules / ".bin/tsx"), "buy-video.ts", env=env)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assert_file("video.mp4", MP4)
        self.assertEqual(self.asked("x402/video")[0], {"prompt": "a paper boat drifting down a rain-filled gutter at dawn", "aspectRatio": "9:16"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
