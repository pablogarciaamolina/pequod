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

Sent messages and replies are stored in `runs/mock_hub.db` (config key `mock_hub`). For real platforms see "Live channels" below.

### Play it in the browser (simulator)

The simulator is a page where you play the client and follow the engine. It is a separate program (`src/pequod_sim/`);
the engine runs the same way with or without it.

Start both in the repository folder, each in its own terminal:

```
uv run pequod-sim        # then open http://127.0.0.1:8000
uv run pequod            # the engine; add overrides as above
```

| Part of the page | What it does |
|---|---|
| Left: channels | Pick email, SMS or WhatsApp. A number shows messages you have not looked at yet. |
| Middle: conversation | The engine's messages on that channel. Type a reply as the client and press Enter. |
| Right: engine | What the engine is doing now, one card per finished wave, and the final report. |

The three buttons do the same as the terminal keys and are active while the engine waits:
"Send now" (`s`), "Next iteration" (Enter), "Stop" (`q`).

Notes:
- A new run empties the inboxes. Older runs stay in their `runs/<start time>/` folder.
- The page only shows mock channels. Its settings are in `configs/sim.yaml` (host, port, refresh time).
- The server listens on this machine only and has no login.

### Explain a run

Every run writes its record into its own folder, `runs/<start time>/`:

| File | Content |
|---|---|
| `trace.jsonl` | one line per wave: the paths, what was sent, the replies absorbed, the stop signal, the decision |
| `messages.jsonl` | every message sent and every reply received, in full, in the order they happened |
| `status.json` | what the engine is doing right now (read by the simulator) |
| `graph_0.json`, `graph_1.json`, ... | the knowledge graph over time. `graph_0` is the start; `graph_<n>` is the graph after the replies of wave n were absorbed. Wave n was planned from `graph_<n-1>`. |
| `report.md` | the final report for the supervisor, with the stop reason on the first line |
| `main.log`, `.hydra/` | the log and the full config of the run (written by Hydra) |

Print one card per wave, then the report:

```
uv run pequod explain runs/2026-11-14_19-10-00
```

This also works while the run is still in progress.

### Live channels (real email, SMS, WhatsApp)

With `channels=live` the engine sends real messages and reads real replies. Nothing else changes.

**1. Accounts and `.env`.** Copy `.env.example` to `.env` and fill in only the channels you use:

| Channel | You need | Variables in `.env` |
|---|---|---|
| Email | A Gmail account with 2-step verification and an app password (Google account → Security → App passwords) | `EMAIL_ADDRESS`, `EMAIL_APP_PASSWORD` |
| SMS | A Twilio account and a Twilio phone number | `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_SMS_FROM` |
| WhatsApp | The Twilio WhatsApp sandbox; the recipient first sends the sandbox's join code to Twilio's number | `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_WHATSAPP_FROM` |

Phone numbers are written with the country code, for example `+34600111222`.

**2. Who receives the messages.** Open `configs/engagement/live_test.yaml` and replace the placeholder addresses by your own
test addresses. Delete a channel you do not use. Do not commit this file with real addresses in it.
The demo persona's addresses are placeholders; a live run with them stops before anything is sent.

**3. Try one channel** (no model is used):

```
uv run pequod check email engagement=live_test            # sends one test message
uv run pequod check email replies engagement=live_test    # lists the replies of the last 24 hours
```

**4. Run an engagement:**

```
uv run pequod channels=live engagement=live_test
```

Control it with the terminal keys (`s`, Enter, `q`). The simulator page is for mock channels only.

Limits:
- Replies are read when an iteration starts: after the reply window, or when you press Enter.
- WhatsApp sandbox: free-text messages only reach the recipient within 24 hours after their last message to the sandbox.
- Email replies must come from the address in the engagement file and arrive in the inbox of `EMAIL_ADDRESS`.
- Mail servers other than Gmail: change `smtp_host`, `smtp_port` and `imap_host` in `configs/channels/live.yaml`.

### Keeping no record of a run

```
uv run pequod run.register=false
```

With `run.register=false` (mock or live) the run folder gets no `trace.jsonl`, `messages.jsonl`, graph snapshots or `report.md`,
and `main.log` keeps the engine's steps without the message texts and without the report. Everything is still shown in the
terminal. `pequod explain` cannot explain such a run. Two things are still stored: the run's settings in `runs/<start time>/.hydra/`
(they include the engagement file), and, in mock mode, the current run's messages in the mock hub until the next run starts.

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
