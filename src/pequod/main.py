"""Hydra entry: build objects, run the loop."""

import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import hydra
from dotenv import load_dotenv
from hydra import compose, initialize_config_dir
from hydra.core.hydra_config import HydraConfig
from hydra.errors import HydraException
from hydra.utils import to_absolute_path
from omegaconf import DictConfig, OmegaConf

from pequod.agents.base import AgentError
from pequod.agents.composer import Composer
from pequod.agents.planner import Planner
from pequod.agents.resolver import Resolver
from pequod.agents.reviewer import Reviewer
from pequod.agents.strategist import Strategist
from pequod.agents.updater import Updater
from pequod.channels import build_channels
from pequod.channels.base import ChannelError
from pequod.channels.mock_hub import MockHub
from pequod.engagement import Agents, EngagementLoop, Operator, Scheduler
from pequod.graph import KnowledgeGraph
from pequod.models.base import build_named
from pequod.strategies import StrategyCatalog
from pequod.trace import Trace
from pequod.types import Engagement, Interaction

log = logging.getLogger(__name__)

# Absolute: as a console script, Hydra reads a relative config_path as a package.
CONFIGS = str(Path(__file__).parents[2] / "configs")
USAGE = 'Usage: pequod reply <channel> "text"'
EXPLAIN_USAGE = "Usage: pequod explain <run folder>   (for example runs/2026-11-14_19-10-00)"
CHECK_USAGE = "Usage: pequod check <channel> [replies] [overrides]   (for example: pequod check email engagement=live_test)"
CHECK_TEXT = "This is a test message from Pequod. You can reply to it."


def now() -> datetime:
    return datetime.now(timezone.utc)


def reply(args: list[str]) -> int:
    """Answer as the persona: write one reply into the mock hub. Returns the exit code."""
    if len(args) != 2 or not args[1].strip():
        print(USAGE, file=sys.stderr)
        return 2
    channel, text = args
    with initialize_config_dir(config_dir=CONFIGS, version_base=None):
        cfg = compose(config_name="config")
    hub = MockHub(cfg.mock_hub)
    channels = hub.channels() or cfg.engagement.channels  # the running run's channels, if a run has started
    if channel not in channels:
        print(f"Unknown channel '{channel}'. Use one of: {', '.join(channels)}", file=sys.stderr)
        return 2
    hub.add_reply(channel, text, now())
    print(f"Reply stored on {channel} ({hub.path.resolve()}).")
    return 0


def explain(args: list[str]) -> int:
    """Print one card per wave of a run, then its report. Returns the exit code."""
    if len(args) != 1:
        print(EXPLAIN_USAGE, file=sys.stderr)
        return 2
    if not Path(args[0]).is_dir():
        print(f"No such run folder: {args[0]}", file=sys.stderr)
        return 2
    try:
        print(Trace(args[0]).explain())
    except FileNotFoundError as e:
        print(e, file=sys.stderr)
        return 2
    return 0


def check(args: list[str]) -> int:
    """Try one live channel without a model: send one fixed test message, or (`replies`) list the replies
    of the last 24 hours. Always uses channels=live. Returns the exit code."""
    if not args:
        print(CHECK_USAGE, file=sys.stderr)
        return 2
    name, *rest = args
    replies = rest[:1] == ["replies"]
    load_dotenv()
    try:
        with initialize_config_dir(config_dir=CONFIGS, version_base=None):
            cfg = compose(config_name="config", overrides=["channels=live", *rest[replies:]])
    except HydraException as e:
        print(f"{CHECK_USAGE}  [{str(e).splitlines()[0]}]", file=sys.stderr)
        return 2
    if name not in cfg.engagement.channels:
        print(f"Unknown channel '{name}'. Use one of: {', '.join(cfg.engagement.channels)}", file=sys.stderr)
        return 2
    if cfg.channels[name].mode != "live":
        print(f"`pequod check` is for live channels; {name} is set to {cfg.channels[name].mode}.", file=sys.stderr)
        return 2
    address = cfg.engagement.channels[name].address
    try:
        channel = build_channels(cfg.channels, {name: address}, None, now)[name]
        if replies:
            found = channel.fetch_replies(now() - timedelta(hours=24))
            print(f"{len(found)} reply(ies) from {address} on {name} in the last 24 hours.")
            for r in found:
                print(f"- {r.received_at.isoformat()}: {r.body}")
        else:
            sent = channel.send(Interaction(channel=name, send_at=now(), body=CHECK_TEXT, subject="Pequod test"))
            print(f"Test message sent to {address} on {name} (id {sent}).")
    except ValueError as e:  # missing credentials or a placeholder address: nothing was sent
        print(e, file=sys.stderr)
        return 2
    except ChannelError as e:
        print(e, file=sys.stderr)
        return 1
    return 0


def open_hub(cfg: DictConfig) -> MockHub | None:
    """The mock hub is the simulator's store: used when a mock channel is configured, never in a live run."""
    used = [cfg.channels[name] for name in cfg.engagement.channels if name in cfg.channels]
    if not any(channel.mode == "mock" for channel in used):
        return None
    return MockHub(to_absolute_path(cfg.mock_hub))  # relative to the start folder, like `pequod reply`


def build_loop(cfg: DictConfig, operator: Operator, folder: str | Path) -> EngagementLoop:
    """Every object of a run, built from the config. `folder` receives the trace, snapshots and report."""

    def model(agent: str):
            label = cfg.agents[agent].model
            if label not in models:  # agents with the same label share one model object
                models[label] = build_named(cfg.models, label)
            return models[label]

    
    hub = open_hub(cfg)
    if hub:
        hub.start_run(folder)  # first: the simulator shows this run from now on, also if it fails right below
    engagement = Engagement.model_validate(OmegaConf.to_container(cfg.engagement, resolve=True))
    run, angle = cfg.run, cfg.angle.text
    if run.max_paths > len(engagement.channels):
        raise ValueError(
            f"run.max_paths is {run.max_paths} but the engagement has {len(engagement.channels)} channels; "
            "each path needs its own channel"
        )
    addresses = {name: channel.address for name, channel in engagement.channels.items()}
    if hub:
        hub.set_channels(addresses)  # the simulator and `pequod reply` follow the run, not the default config
    channels = build_channels(cfg.channels, addresses, hub, now)
    rules = {name: channel.rules for name, channel in channels.items()}
    graph = KnowledgeGraph.from_engagement(engagement)
    catalog = StrategyCatalog.from_config(cfg.strategies)

    roles = {name: cfg.channels[name].role for name in channels if cfg.channels[name].role}
    lines = ["Who we write as on each channel:", *(f"- {name}: {text}" for name, text in roles.items())]
    role = "\n".join(lines) if roles else ""  # added to the prompts like the angle

    models = {}

    steps = {name: agent.max_steps for name, agent in cfg.agents.items()}
    agents = Agents(
        strategist=Strategist(model("strategist"), graph, steps["strategist"], run.max_paths, role),
        planner=Planner(model("planner"), graph, catalog, rules, steps["planner"], run.max_waves, angle, role),
        composer=Composer(model("composer"), graph, catalog, rules, steps["composer"], angle, role),
        reviewer=Reviewer(model("reviewer"), graph, rules, steps["reviewer"], angle, role),
        updater=Updater(model("updater"), graph, steps["updater"]),
        resolver=Resolver(model("resolver"), graph, steps["resolver"], angle),
    )
    trace = Trace(folder, run.register)
    scheduler = Scheduler(channels, operator, run.reply_window_h, now, on_send=trace.sent)
    return EngagementLoop(engagement.objective, agents, channels, scheduler, run.max_iterations, now, graph, trace)


@hydra.main(version_base=None, config_path=CONFIGS, config_name="config")
def run(cfg: DictConfig) -> None:
    load_dotenv()  # API keys and credentials from .env
    operator = Operator(hub=open_hub(cfg), poll_s=cfg.run.command_poll_s)
    sys.exit(play(cfg, operator, HydraConfig.get().runtime.output_dir))


def play(cfg: DictConfig, operator: Operator, folder: str | Path) -> int:
    """One run. Returns the exit code. However the run ends, its status says so (the simulator reads it)."""
    register = cfg.run.register
    files = [h for h in logging.getLogger().handlers if isinstance(h, logging.FileHandler)]
    if not register:  # the terminal still shows the texts; the log file of the run does not keep them
        for handler in files:
            handler.addFilter(no_text)
    try:
        build_loop(cfg, operator, folder).run()
    except (AgentError, ChannelError, ValueError) as e:
        Trace(folder, register).fail(brief(e, register))
        log.error("Run stopped: %s", brief(e, register))
        logging.getLogger("pequod.text").error("Details: %s", e, exc_info=e.__cause__ is not None)
        return 1
    except BaseException as e:  # Ctrl+C or a bug: mark the run, then let it surface
        Trace(folder, register).fail(f"{type(e).__name__}: {e}".rstrip(": "))
        raise
    finally:
        for handler in files:
            handler.removeFilter(no_text)
    return 0


def brief(error: Exception, register: bool) -> str:
    """The error as it is stored. With the register off, nothing that could quote a model or a persona:
    an agent's failure keeps its first sentence, a wrapped library error only its type."""
    message = str(error)
    if register or not isinstance(error, AgentError):
        return message
    if error.__cause__ is not None:
        return f"{message.split(':')[0]}: {type(error.__cause__).__name__}"
    return message.split(" Last message:")[0]


def no_text(record: logging.LogRecord) -> bool:
    """Log filter: drop what the engine planned, said and learned (logger `pequod.text`)."""
    return record.name != "pequod.text"


def main() -> None:
    """Console entry. `pequod reply|explain|check ...` are handled here; the rest goes to Hydra."""
    for stream in (sys.stdout, sys.stderr):  # messages can hold any character; a Windows pipe is not UTF-8
        stream.reconfigure(encoding="utf-8", errors="replace")
    commands = {"reply": reply, "explain": explain, "check": check}
    if sys.argv[1:2] and sys.argv[1] in commands:
        sys.exit(commands[sys.argv[1]](sys.argv[2:]))
    run()
