"""Hydra entry: build objects, run the loop."""

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import hydra
from dotenv import load_dotenv
from hydra import compose, initialize_config_dir
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
from pequod.channels.mock_hub import MockHub
from pequod.engagement import Agents, EngagementLoop, Operator, Scheduler
from pequod.graph import KnowledgeGraph
from pequod.models.base import build_named
from pequod.strategies import StrategyCatalog
from pequod.types import Engagement

log = logging.getLogger(__name__)

# Absolute: as a console script, Hydra reads a relative config_path as a package.
CONFIGS = str(Path(__file__).parents[2] / "configs")
USAGE = 'Usage: pequod reply <channel> "text"'


def now() -> datetime:
    return datetime.now(timezone.utc)


def reply(args: list[str]) -> int:
    """Answer as the client: write one reply into the mock hub. Returns the exit code."""
    if len(args) != 2 or not args[1].strip():
        print(USAGE, file=sys.stderr)
        return 2
    channel, text = args
    with initialize_config_dir(config_dir=CONFIGS, version_base=None):
        cfg = compose(config_name="config")
    if channel not in cfg.engagement.channels:
        print(f"Unknown channel '{channel}'. Use one of: {', '.join(cfg.engagement.channels)}", file=sys.stderr)
        return 2
    hub = MockHub(cfg.mock_hub)
    hub.add_reply(channel, text, now())
    print(f"Reply stored on {channel} ({hub.path.resolve()}).")
    return 0


def build_loop(cfg: DictConfig, operator: Operator) -> EngagementLoop:
    """Every object of a run, built from the config."""

    def model(agent: str):
            label = cfg.agents[agent].model
            if label not in models:  # agents with the same label share one model object
                models[label] = build_named(cfg.models, label)
            return models[label]

    
    engagement = Engagement.model_validate(OmegaConf.to_container(cfg.engagement, resolve=True))
    run, angle = cfg.run, cfg.angle.text
    if run.max_paths > len(engagement.channels):
        raise ValueError(
            f"run.max_paths is {run.max_paths} but the engagement has {len(engagement.channels)} channels; "
            "each path needs its own channel"
        )
    hub = MockHub(to_absolute_path(cfg.mock_hub))  # relative to the start folder, like `pequod reply`
    channels = build_channels(cfg.channels, engagement.channels, hub, now)
    rules = {name: channel.rules for name, channel in channels.items()}
    graph = KnowledgeGraph.from_engagement(engagement)
    catalog = StrategyCatalog.from_config(cfg.strategies)

    models = {}

    steps = {name: agent.max_steps for name, agent in cfg.agents.items()}
    agents = Agents(
        strategist=Strategist(model("strategist"), graph, steps["strategist"], run.max_paths),
        planner=Planner(model("planner"), graph, catalog, rules, steps["planner"], run.max_waves, angle),
        composer=Composer(model("composer"), graph, catalog, rules, steps["composer"], angle),
        reviewer=Reviewer(model("reviewer"), graph, rules, steps["reviewer"], angle),
        updater=Updater(model("updater"), graph, steps["updater"]),
        resolver=Resolver(model("resolver"), graph, steps["resolver"], angle),
    )
    scheduler = Scheduler(channels, operator, run.reply_window_h, now)
    return EngagementLoop(engagement.objective, agents, channels, scheduler, run.max_iterations, now)


@hydra.main(version_base=None, config_path=CONFIGS, config_name="config")
def run(cfg: DictConfig) -> None:
    load_dotenv()  # API keys and credentials from .env
    try:
        build_loop(cfg, Operator()).run()
    except (AgentError, ValueError, NotImplementedError) as e:
        log.error("Run stopped: %s", e, exc_info=e.__cause__ is not None)  # traceback for unexpected causes
        sys.exit(1)


def main() -> None:
    """Console entry. `pequod reply ...` is handled here; everything else goes to Hydra."""
    if sys.argv[1:2] == ["reply"]:
        sys.exit(reply(sys.argv[2:]))
    run()
