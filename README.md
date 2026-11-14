# Pequod

Agentic, multi-wave, multi-channel client-engagement engine. Take-home case for Revel8.
Demo only. The persona (Alex Carter) and company (Northwind Labs) are fictional.

Design: `docs/design-discussion.md`.

## Setup

```
uv sync
```

## Run

```
uv run pequod --help
```

Only the `pequod` entry point is supported. Do not run `python src/pequod/main.py` directly.

### Play an engagement (mock channels)

You need two terminals, both started in the repository folder.

Terminal 1, the engine:

```
uv run pequod
```

Any config value can be changed on the command line, for example the model of every agent:

```
uv run pequod agents.strategist.model=ollama_qwen agents.planner.model=ollama_qwen agents.composer.model=ollama_qwen agents.reviewer.model=ollama_qwen agents.updater.model=ollama_qwen agents.resolver.model=ollama_qwen
```

Each iteration the engine plans, writes and reviews its messages, then waits. Every sent message is printed. While it waits, type:

| Key | Effect |
|---|---|
| `s` + Enter | send all pending messages now (otherwise each one is sent at its planned time) |
| Enter | go to the next iteration; messages not sent yet are dropped |
| `q` + Enter | stop the engagement; the final report is still written |

Terminal 2, you as the client (Alex):

```
uv run pequod reply whatsapp "Honestly, our stock numbers are a day old."
```

Replies can be sent at any time, on any channel. The engine reads them at the start of the next iteration.

The run ends with a report for the supervisor when the client states the root problem, accepts a solution, opts out,
when `run.max_iterations` is reached, or when you press `q`. The log of a run is saved in `runs/<time>/main.log`.

Sent messages and replies are stored in `runs/mock_hub.db` (config key `mock_hub`). `channels=live` is not available yet.

## Test

```
uv run pytest
```

## Models

Models are listed in `configs/config.yaml` under `models` as `label: {provider, name, params}`. The label is free; each agent picks a model by its label under `agents`.
Providers: `anthropic`, `ollama`, `openai`, `vllm`, `huggingface`. API keys go in `.env` (names in `.env.example`).

### Local Hugging Face weights

```yaml
models:
  # runs on Hugging Face's servers (needs HF_TOKEN)
  hf_qwen_hosted: {provider: huggingface, name: Qwen/Qwen2.5-72B-Instruct}
  # downloads the weights and runs on this machine
  hf_qwen_local: {provider: huggingface, name: Qwen/Qwen2.5-1.5B-Instruct, params: {local: true, family: qwen, pipeline_kwargs: {max_new_tokens: 512, do_sample: false}}}
```

With hosted models, the provider's server writes the tools into the prompt and returns tool calls.
With local weights there is no server, so Pequod does both (`src/pequod/models/huggingface.py`):
the model's own chat template writes the tools into the prompt, and the tool calls are read from the generated text.
Each family writes tool calls differently, so `family` is required.

| `family` | Format the model writes | Calls per step | Models checked |
|---|---|---|---|
| `qwen` | `<tool_call>{"name": ..., "arguments": {...}}</tool_call>` | several | `Qwen/Qwen2.5-1.5B-Instruct` (run). Other `Qwen2.5-*-Instruct` sizes use the same template. |
| `llama` | `{"name": ..., "parameters": {...}}` | one | `Llama-3.2-1B-Instruct` (run, see note), `Llama-3.1-8B-Instruct` (template only) |
| `mistral` | `[{"name": ..., "arguments": {...}}]` | several | `Mistral-7B-Instruct-v0.3`, `Mistral-Nemo-Instruct-2407` (template only, not run) |

Notes:
- Other models of a family may use another format. Check the model's chat template before adding one.
- Llama and Mistral repos of Meta and Mistral AI are gated: accept the license on huggingface.co and set `HF_TOKEN` in `.env`.
- Llama: the 1B model often writes a malformed tool call; use 3B or larger. The template adds today's date to the prompt.
- Mistral: the template drops the system prompt after a tool call, so Pequod puts it into the first user message.
- Set `max_new_tokens`: a cut-off answer cannot be read as a tool call.
- `uv sync` installs the CPU build of `torch`. Large models need a GPU build or a hosted provider.
