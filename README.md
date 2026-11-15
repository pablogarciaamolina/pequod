# Pequod

Agentic, multi-wave, multi-channel engine that pursues one objective by engaging a persona across channels. Take-home case for Revel8.
Demo only. The persona (Alex Carter) and company (Northwind Labs) are fictional.

Design: `docs/design-discussion.md`. Decisions taken while building: `docs/DECISIONS.md`.

**Contents**

1. [Setup](#setup)
2. [Commands at a glance](#commands-at-a-glance)
3. [How one run works](#how-one-run-works)
4. [Run it](#run-it): terminal, browser simulator, explain, live channels, no record
5. [Change it](#change-it): engagement, angle, prompts, strategies, channels, models, limits
6. [After a change: what to run](#after-a-change-what-to-run)
7. [Models](#models)

## Setup

```
uv sync
```

Run this again whenever `pyproject.toml` changes. On this machine the project lives in a Google Drive folder, and `uv sync`
sometimes ends with "Acceso denegado ... pequod-0.1.0.dist-info": run it a second time. For the same reason `uv add <package>`
fails; add the package to `pyproject.toml` by hand and run `uv sync`.

Code changes need no reinstall: the project is installed in editable mode.

## Commands at a glance

All commands are started in the repository folder.

| Command | What it does |
|---|---|
| `uv run pequod` | Runs one engagement with the settings in `configs/`. |
| `uv run pequod <key>=<value> ...` | The same with settings changed for this run, for example `angle=empathy run.max_iterations=2`. |
| `uv run pequod --help` | Lists the config groups and the full config. |
| `uv run pequod reply <channel> "text"` | You answer as the persona on a mock channel. |
| `uv run pequod-sim` | Starts the browser simulator at `http://127.0.0.1:8000`. |
| `uv run pequod explain runs/<start time>` | Prints one card per wave of a run, then its report. |
| `uv run pequod check <channel> [overrides]` | Live channels: sends one test message. No model is used. |
| `uv run pequod check <channel> replies [overrides]` | Live channels: lists the replies of the last 24 hours. |
| `uv run pytest` | Runs the tests (fake models, fake servers, no network). |
| `uv run pytest -m live` | Calls each model in `configs/config.yaml` once for real. |

Only these entry points are supported. Do not run `python src/pequod/main.py` directly.

## How one run works

One run is a loop of iterations. In each iteration, six agents work in this order:

| Step | Agent | What it does | File |
|---|---|---|---|
| update | Updater | Writes what was sent and what the persona replied into the knowledge graph. Decides whether to stop. | `src/pequod/agents/updater.py` |
| plan | Strategist | Reads the graph and proposes up to `run.max_paths` paths (ordered subgoals). | `src/pequod/agents/strategist.py` |
| plan | Planner | Turns each path into up to `run.max_waves` waves: intent, strategy, channel, send time. | `src/pequod/agents/planner.py` |
| act | Composer | Writes the message for the first wave of each path. Each path gets its own channel. | `src/pequod/agents/composer.py` |
| act | Reviewer | Polishes all messages of the iteration together. | `src/pequod/agents/reviewer.py` |
| wait | (code) | Sends each message at its time, then waits for replies or for you. | `src/pequod/engagement.py` |
| resolve | Resolver | When the run stops: writes the report for the supervisor. Nothing is sent to the persona. | `src/pequod/agents/resolver.py` |

Only the first wave of each path is sent. The next iteration plans again from the updated graph.

The run stops when the persona meets the objective, accepts a proposal or opts out (decided by the Updater), when
`run.max_iterations` is reached, or when you stop it.

## Run it

### In the terminal (mock channels)

You need two terminals.

Terminal 1, the engine:

```
uv run pequod
```

Each iteration the engine plans, writes and reviews its messages, then waits. Every sent message is printed. While it waits, type:

| Key | Effect |
|---|---|
| `s` + Enter | send all pending messages now (otherwise each one is sent at its planned time) |
| Enter | go to the next iteration; messages not sent yet are dropped |
| `q` + Enter | stop the engagement; the final report is still written |

Terminal 2, you as the persona:

```
uv run pequod reply whatsapp "Honestly, our stock numbers are a day old."
```

Replies can be sent at any time, on any channel of the run. The engine reads them at the start of the next iteration.

Sent messages and replies of the current run are stored in `runs/mock_hub.db` (config key `mock_hub`). A new run empties it.

### In the browser (simulator)

The simulator is a page where you play the persona and follow the engine. It is a separate program (`src/pequod_sim/`);
the engine runs the same way with or without it.

Start both, each in its own terminal:

```
uv run pequod-sim        # then open http://127.0.0.1:8000
uv run pequod            # the engine, with any overrides
```

| Part of the page | What it does |
|---|---|
| Left: channels | The channels of the running run. A number shows messages you have not looked at yet. |
| Middle: conversation | The engine's messages on that channel. Type a reply as the persona and press Enter. |
| Right: engine | What the engine is doing now, one card per finished wave, and the final report. |

The three buttons do the same as the terminal keys and are active while the engine waits:
"Send now" (`s`), "Next iteration" (Enter), "Stop" (`q`).

Notes:
- The page only shows mock channels. Its settings are in `configs/sim.yaml` (host, port, refresh time).
- The server listens on this machine only and has no login.
- Start `pequod-sim`, `pequod` and `pequod reply` in the same folder and do not override `mock_hub`: they find each other through that file.

### Explain a run

Every run writes its record into its own folder, `runs/<start time>/`:

| File | Content |
|---|---|
| `trace.jsonl` | one line per wave: the paths, what was sent, the replies absorbed, the stop signal, the decision |
| `messages.jsonl` | every message sent and every reply received, in full, in the order they happened |
| `status.json` | what the engine is doing right now (read by the simulator) |
| `graph_0.json`, `graph_1.json`, ... | the knowledge graph over time. `graph_0` is the start; `graph_<n>` is the graph after the replies of wave n were absorbed. Wave n was planned from `graph_<n-1>`. |
| `report.md` | the final report for the supervisor, with the stop reason on the first line |
| `main.log` | the log of the run, including every agent step |
| `.hydra/config.yaml` | the full config the run used |

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
test addresses. Do not commit this file with real addresses in it. You can delete a channel you do not use; with one channel
left, also pass `run.max_paths=1` (each path needs its own channel).

A live run stops before anything is sent when a credential is missing, when an address is a placeholder
(the demo persona's, `example.com`, a number made of zeros), or when the persona's address is the same as your own sender address.

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
- Email replies must come from the address in the engagement file and arrive in the inbox (not spam) of `EMAIL_ADDRESS`.
- A link from a strategy is added as a last line when the text does not contain it. An SMS can then exceed 160 characters and be billed as two.
- The live channels were tested against fake servers only. See the checklist in `docs/reviews/stage-6.md`.

### Keeping no record of a run

```
uv run pequod run.register=false
```

With `run.register=false` (mock or live) the run folder gets no `trace.jsonl`, `messages.jsonl`, graph snapshots or `report.md`,
and `main.log` keeps the engine's steps without the message texts and without the report. Everything is still shown in the
terminal. `pequod explain` cannot explain such a run. Two things are still stored: the run's settings in `runs/<start time>/.hydra/`
(they include the engagement file), and, in mock mode, the current run's messages in the mock hub until the next run starts.

## Change it

### Where things are

| You want to change | File | Reinstall? |
|---|---|---|
| The persona, the objective, their channels | `configs/engagement/<name>.yaml` | no |
| The tone | `configs/angle/<name>.yaml` | no |
| What an agent is told | `PROMPT` in `src/pequod/agents/<agent>.py` | no |
| What an agent must return | the classes in `src/pequod/types.py` | no |
| The catalog of strategies and their links | `configs/strategies/<name>.yaml` | no |
| Length and subject rules of a channel | `rules` in `configs/channels/mock.yaml` and `live.yaml` | no |
| A new channel or a second account | `src/pequod/channels/`, `configs/channels/` | no |
| Which model each agent uses, step limits | `agents` and `models` in `configs/config.yaml` | no |
| Loop limits, reply window | `run` in `configs/config.yaml` | no |
| A new Python package | `pyproject.toml` | `uv sync` |

Two ways to use a config change:

- **For one run:** on the command line. `uv run pequod angle=empathy run.max_iterations=3 agents.composer.max_steps=6`
- **As the new default:** edit the file, or the `defaults` list at the top of `configs/config.yaml`
  (`engagement`, `angle`, `channels`, `strategies` each name one file of their folder).

A tip that saves broken tests: for a new persona, tone or strategy set, **add a new file and select it**
(`engagement=acme`, `angle=direct`, `strategies=rich`) instead of editing the default one. Several tests check the content of the default files.

### A new persona (engagement)

Copy `configs/engagement/alex_carter.yaml` to `configs/engagement/acme.yaml` and edit it:

```yaml
objective: "Find out which accounting software the persona uses."
persona:
  name: Jamie Rivera
  features:                 # free keys and values; all of them go into the knowledge graph
    role: Finance lead
    timezone: Europe/Madrid
    comms_style: formal
    notes: "Complained about invoice delays in March."
channels:                   # only channels listed here are used; each needs an entry in configs/channels/
  email:
    address: jamie@acme.example
    features: {hours: "09-13", notes: "prefers email"}   # free keys; the Planner reads them
  whatsapp:
    address: "+00 000 000"
    features: {hours: "10-18"}
```

```
uv run pequod engagement=acme
```

- Everything under `features` is free text for the agents. Nothing in code depends on the key names. The prompts refer to the
  persona's timezone and communication style and to each channel's `hours` and notes, so keeping keys with those names helps.
- `run.max_paths` must not be larger than the number of channels.

### The tone (angle)

One file per angle in `configs/angle/`: `clarity`, `empathy`, `reassurance`, `curiosity`, `helpfulness`.

```yaml
# configs/angle/direct.yaml
name: direct
text: "Be direct: say what you need in the first sentence and give one deadline."
```

```
uv run pequod angle=direct
```

The `text` is added at the end of the prompt of the Planner, Composer, Reviewer and Resolver as "Conversational angle: ...".
The Strategist and the Updater do not get it.

### The prompts

Each agent's prompt is the constant `PROMPT` at the top of its file in `src/pequod/agents/`. Edit the text, save, run again.

What a model sees for one agent, in this order:

| Part | Where it comes from |
|---|---|
| System prompt | `PROMPT` in the agent's file, plus the angle for four agents |
| User message | built in the agent's `run()` method in the same file (objective, paths, drafts, replies, current time, limits) |
| Tools | set in the agent's `__init__`: graph read tools for all; `list_strategies` and `channel_rules` for some; graph write tools for the Updater only |
| Answer format | the agent's output class in `src/pequod/types.py`. Its docstring and field descriptions are shown to the model, so they are part of the prompt. |

| Agent | Output class | Checked in code after the model answers |
|---|---|---|
| Strategist | `Paths` | at most `run.max_paths` paths (extra ones are cut) |
| Planner | `Paths` with waves | same number of paths, each with at least one wave; at most `run.max_waves` waves (extra ones are cut) |
| Composer | `Interaction` | channel exists and is not taken by another path; `payload` is empty or copied from the catalog for that channel; length and subject fit the channel's rules |
| Reviewer | `Review` | same channels in the same order; payloads unchanged; length and subject rules |
| Updater | `StopSignal` | (nothing; it writes to the graph through its tools) |
| Resolver | `Resolution` | (nothing) |

When a check fails, the error text goes back to the model and it tries again, up to the agent's `max_steps` model calls
(`agents.<name>.max_steps` in `configs/config.yaml`). If it still has no valid answer, the run stops and names the agent.

Things to know before you rewrite a prompt:

- The stop decision is the Updater's. The rules for `objective_met`, `solution_accepted` and `opt_out` are at the end of its prompt.
- The Updater's prompt must not contain the hidden answer of your case: the engine is supposed to find it. A test guards the demo's answer (the words sync, night, warehouse, stock); change those words in the test if your case's answer differs.
- The Resolver's prompt fixes the sections of the report.
- The Planner's prompt lists the starting intents (`open_door`, `build_rapport`, `check_precondition`, `ask_directly`, `ask_indirectly`, `follow_up`, `clarify`, `confirm`). Intents are free text; you can add or rename them there.
- Tests on prompts are few: every agent has a `PROMPT` of some length, no prompt contains the word "ignored", and the Updater's rule above.
- To see what an agent really did, read `runs/<start time>/main.log`, or run `uv run pequod explain runs/<start time>`.

### The strategies

A strategy is one way to make a contact. Every message is built on one. The catalog is `configs/strategies/default.yaml`:
24 strategies written for any objective and any persona, grouped by the state of the conversation.

| Situation | Strategies |
|---|---|
| Opening (nothing said yet) | `plain_message`, `introduce`, `warm_opener` |
| Asking | `direct_ask`, `indirect_ask`, `choice_question`, `yes_no_check`, `assumption_check`, `open_invitation`, `shared_interest`, `give_first` |
| After a reply | `build_on_reply`, `clarify`, `confirm_back`, `thank_and_close` |
| After silence | `gentle_nudge`, `rephrase`, `smaller_ask`, `channel_switch` |
| After hesitation or refusal | `explain_why`, `easy_out` |
| With a link (example links: replace them with yours) | `info_link`, `call_link`, `form_link` |

Every description has two parts: what to do, then "Use ...": when to choose it. A test checks that the second part is there.

To add strategies, edit that file, or write your own catalog and select it:

```yaml
# configs/strategies/rich.yaml
plain_message: {description: "A plain message. Use when no other strategy fits.", channels: [email, sms, whatsapp]}
case_study:    {description: "Share a one-page story about a similar case. Use when the persona doubts that we can help.", payload: {url: "https://example.com/story.pdf"}, channels: [email]}
quick_poll:    {description: "Ask one multiple-choice question (A/B/C) the persona can answer with a letter. Use on short channels.", channels: [sms, whatsapp]}
```

```
uv run pequod strategies=rich
```

| Field | Meaning |
|---|---|
| the key (`case_study`) | the id the Planner writes into a wave |
| `description` | what the Planner and Composer read to decide when and how to use it. This is the place to be precise. |
| `channels` | where it may be used |
| `payload` (optional) | a fixed link or asset, as free `name: value` pairs. The Composer may only attach a payload that is in the catalog for that channel. |

How the agents use the catalog:

- The Planner and the Composer read it through the tool `list_strategies` (all, or only those of one channel).
- The catalog is a base, not a limit: the Planner may also describe a **custom strategy** in a few words. A custom strategy can use plain text or a
  payload from the catalog. It can never bring its own link: code rejects any payload that is not in the catalog.
- So: to make a new link or asset usable, it must be in the catalog. To make a new *kind of contact* usable, a good `description` is enough, and often
  a sentence in the Planner's prompt on when to prefer it.

### Who the engine writes as (role)

You state the role, per channel, in the channel config: who we write as on that channel. It can be any character
or company. Set it to match the account the channel sends from. An empty role means "an assistant monitored by a human".

```yaml
# configs/channels/mock.yaml and configs/channels/live.yaml (keep both the same)
email:
  role: "Sam from Paws & Co, a small pet shop. Writes to customers about their pets."
whatsapp:
  role: ""
```

Or for one run, without editing a file:

```
uv run pequod "channels.email.role='Sam from Paws & Co, a small pet shop'"
```

- The roles are added to the system prompt of the Strategist, Planner, Composer and Reviewer, before the angle,
  as a list "Who we write as on each channel". Only the channels of the engagement are listed.
- No agent chooses or changes a role. The Composer writes each message as the role of its channel.
- What a role may never do is one line starting with "Limits:" in the `PROMPT` of the Strategist, Planner, Composer,
  Reviewer and Resolver. It exists only there: to change it, edit it in those five files (a test checks they match).
- This overrides design line 47 ("the client already knows an engine answers"), see D64.

### The channels

A channel has three parts:

| Part | Where |
|---|---|
| Rules: maximum length, subject line yes/no, links yes/no | `rules` in `configs/channels/mock.yaml` and `configs/channels/live.yaml` (keep both the same) |
| Mock and live class | `src/pequod/channels/email.py`, `sms.py`, `whatsapp.py` |
| Live settings and credentials | `configs/channels/live.yaml`: server settings, and `credentials` (what the class needs → name of the variable in `.env`) |

**Change a rule** (for example longer WhatsApp messages): edit `max_length` in both channel files. The agents read the rules through the tool
`channel_rules`, and code enforces them on every message.

**Use fewer channels:** remove them from the engagement file. Nothing else is needed.

**A second account on the same platform** (for example a second mailbox, `email_sales`). The engine has one sender per channel name,
so a second account is a second channel:

1. In `src/pequod/channels/email.py`, add two small classes:

   ```python
   class EmailSalesMock(EmailMock):
       name = "email_sales"

   class EmailSalesLive(EmailLive):
       name = "email_sales"
   ```

2. In `src/pequod/channels/__init__.py`, add them to the two lists that build `MOCKS` and `LIVE`.
3. In `configs/channels/mock.yaml` and `live.yaml`, add an `email_sales` entry (copy the `email` entry). In `live.yaml`, point its
   `credentials` at other variables, for example `{user: EMAIL_SALES_ADDRESS, password: EMAIL_SALES_APP_PASSWORD}`, and add those to `.env`.
4. In the engagement file, add `email_sales` under `channels` with the persona's address and features. The `notes` are the place to say
   what this account is for ("sales contact; use for offers").
5. In the strategies file, add `email_sales` to the `channels` of every strategy that may use it.

The same recipe works for a second Twilio number (subclass `SmsLive` or `WhatsAppLive`, with another `sender` variable).

**A new platform** (for example Telegram): write a mock class (three lines, like above, on `MockChannel`) and a live class with
`send(interaction) -> id`, `fetch_replies(since) -> list[Reply]` and `from_config(rules, address, settings, secrets)`, following
`EmailLive` or `TwilioChannel`. Then steps 2 to 5 as above. A live class must raise `ChannelError` for platform failures and must never put a
credential into an error text.

After adding a channel name:
- `tests/test_config.py` expects the default channel files and the default engagement to list the same channels. Update that test, or add the new
  channel to `alex_carter.yaml` too.
- In the simulator the new channel appears in the list under its name, with chat-style messages.

### Models and step limits

```yaml
# configs/config.yaml
models:
  ollama_qwen: {provider: ollama, name: "qwen2.5:14b", params: {num_ctx: 8192, temperature: 0}}
  claude: {provider: anthropic, name: claude-sonnet-5-5}

agents:
  strategist: {model: ollama_qwen, max_steps: 4}
  updater:    {model: ollama_qwen, max_steps: 8}
```

- `models`: a free label → provider, model name, and `params` passed to the provider. Add as many as you like.
- `agents`: which label each agent uses, and its `max_steps` (the maximum number of model calls in one agent run; tool executions do not count).
- For one run: `uv run pequod agents.composer.model=claude agents.updater.max_steps=12`.
- API keys go in `.env` (names in `.env.example`).
- Small local models need more steps and make more mistakes. In the test runs, `qwen2.5:14b` needed `max_steps=8` for every agent.

### Loop limits

```yaml
# configs/config.yaml
run:
  max_iterations: 5     # iterations before the run stops by itself
  max_paths: 2          # paths (and so messages) per iteration; not more than the number of channels
  max_waves: 3          # waves planned per path (only the first is sent)
  reply_window_h: 24    # wait after the last send, unless you press Enter
  command_poll_s: 1     # how often the engine looks for the simulator's buttons
  register: true        # false = keep no record of the run
```

## After a change: what to run

| You changed | Run | To see |
|---|---|---|
| A prompt, an angle, a strategy file, an engagement file | `uv run pequod <your overrides> run.max_iterations=1`, with `uv run pequod-sim` open | one iteration with the new behaviour; then `uv run pequod explain runs/<start time>` |
| A prompt | also `uv run pytest tests/test_agents_common.py tests/test_updater.py` | the few prompt rules still hold |
| An output class in `types.py` | `uv run pytest` | the agents and the trace still fit together |
| Channel rules | `uv run pytest tests/test_config.py tests/test_composer.py tests/test_reviewer.py` | rules load and are enforced |
| A new channel or account | `uv run pytest tests/test_channels.py tests/test_live_channels.py tests/test_config.py`, then a mock run, then `uv run pequod check <channel> engagement=<file>` for live | it is built, it sends, it reads |
| Models or `max_steps` | `uv run pytest -m live` | each model in the config answers once for real |
| `pyproject.toml` | `uv sync` (twice if the first try reports "Acceso denegado") | the package is installed |
| Anything in `src/` | `uv run pytest` | nothing else broke (about one minute) |

A quick loop for prompt work: keep `uv run pequod-sim` open, run `uv run pequod run.max_iterations=1`, press "Send now", read the messages,
reply, press "Next iteration", read the card and the report.

## Models

Models are listed in `configs/config.yaml` under `models` as `label: {provider, name, params}`. The label is free; each agent picks a model by its label under `agents`.
Providers: `anthropic`, `ollama`, `openai`, `vllm`, `huggingface`. API keys go in `.env` (names in `.env.example`).

Provider notes:
- **Ollama:** set `num_ctx` (the default context is too small for the agents' tool outputs). Ollama ignores forced tool choice; when a model
  answers in plain text, the agent reminds it once per step to use the output tool.
- **vLLM:** start the server with `--enable-auto-tool-choice --tool-call-parser <parser for the model>`, and set `params.base_url`.
- **Anthropic, OpenAI:** set the key in `.env`. The Anthropic model was never called in the test runs.

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
