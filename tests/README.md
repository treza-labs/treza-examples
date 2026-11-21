# Tests

```bash
python3 tests/run_tests.py            # every recipe
python3 tests/run_tests.py ShortsRecipe
```

[`run_tests.py`](run_tests.py) runs each recipe against [`mock_treza.py`](mock_treza.py), a stand-in for Treza's API on `127.0.0.1`. The mock answers with the same fields and refusal codes as Treza, keeps a balance, and records every call, so the tests check the flow itself: a quote first, nothing started over the cap or on a short balance, one start with the quote's `quoteId`, polling until done, and the file downloaded without the key. It needs no key and spends nothing. Each test starts its own mock in an empty temporary folder.

| Tests | Need | Skipped without them |
| --- | --- | --- |
| `CurlRecipe` | bash, curl, jq | yes |
| `PythonRecipe`, `ShortsRecipe` | `requests` | yes |
| `TypeScriptRecipe` | Node 23.6+, or `tsx` on the PATH or in `typescript/node_modules` | yes |
| `NotebookFile` | `nbformat` | yes |
| `NotebookCells` | `nbformat`, `ipython`, `langchain-treza`; `langchain` for the agent cells | yes |
| `Workflows` | nothing | |
| `X402Snippet` | `X402_NODE_MODULES`: a `node_modules` with `@x402/fetch`, `@x402/evm`, `viem` and `tsx` | yes |

The notebook's agent cells run with a scripted chat model in place of Claude, so no Anthropic key is needed. The x402 snippet runs with a throwaway key; the mock answers without a 402 challenge, so nothing is signed or paid.

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install requests nbformat ipython langchain-treza langchain
python tests/run_tests.py
```

Run the mock on its own to try a recipe by hand:

```bash
python3 tests/mock_treza.py --port 8765
TREZA_BASE_URL=http://127.0.0.1:8765 TREZA_API_KEY=treza_live_test ./curl/make-video.sh
```

## Checking the workflows against the real nodes

With checkouts of the node packages, these check every parameter and widget against the nodes' own definitions:

```bash
node tests/check_n8n.cjs ../n8n-nodes-treza n8n/daily-vertical-video.json          # a built checkout (npm run build)
python3 tests/check_comfyui.py ../treza-comfyui comfyui/treza_free_picture_to_vertical_clip.json
```

`run_tests.py` runs them too when `N8N_NODES_TREZA_DIR` and `TREZA_COMFYUI_DIR` point at those checkouts.
