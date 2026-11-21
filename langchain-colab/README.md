# LangChain in Colab

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/treza-labs/treza-examples/blob/main/langchain-colab/treza_langchain_agent.ipynb)

[`treza_langchain_agent.ipynb`](treza_langchain_agent.ipynb) uses [`langchain-treza`](https://github.com/treza-labs/langchain-treza) in two parts:

1. **The tools on their own.** `TrezaBalance` shows your credit balance and `TrezaGenerateImage` makes one of today's free pictures, shown in the notebook. Costs $0.
2. **An agent (optional).** `create_agent` with Claude Sonnet 5.5 (`"anthropic:claude-sonnet-5-5"` through `langchain-anthropic`) and the Treza toolkit makes a 4 second vertical video, played in the notebook. About $0.28 on Treza, plus what Anthropic charges for the agent's tokens. OpenAI or any other LangChain chat model works the same way.

## Cost and spending caps

- The picture cell sets `max_cost_usd=0.01`. A free picture is quoted at $0, so it renders. Once today's 5 free pictures are used up, a picture costs about $0.06 and the tool stops with "over the Max cost", spending nothing.
- The agent's toolkit sets `max_cost_usd=0.50`, the most any one render may cost. The model cannot see or raise it.

## Run

1. Open the notebook in Colab with the badge above, or in Jupyter.
2. Add `TREZA_API_KEY` under **Secrets** (the key icon in Colab's left bar) and allow the notebook to read it, or paste it when asked. Make the key at https://www.trezalabs.com/platform/api-keys with the `pipelines:read`, `pipelines:write` and `pipelines:run` permissions.
3. Run the cells in order. For part 2, also add `ANTHROPIC_API_KEY`.

## Expected output

```
{'balance_usd': 12.4, 'approx_videos_remaining': 22, 'top_up_url': 'https://www.trezalabs.com/platform/settings#billing'}
$0.00 on google/gemini-2.5-flash-image: https://media.trezalabs.com/...
[the picture]

Here is your hummingbird video: ...
$0.28 on google/veo-3.1-lite: https://media.trezalabs.com/...
[the video]
```

The video cell reads the link from the tool's own answer, not from the agent's reply. A render still going after the tool's wait (300 seconds) comes back with `"status": "running"`, a `run_id` and a `pipeline_id`; `TrezaGetRun` picks it up later without starting a second render.
