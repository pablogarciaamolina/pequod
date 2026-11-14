import pytest
from hydra import compose, initialize_config_dir
from omegaconf import OmegaConf

from pequod.main import CONFIGS


def load(overrides=()):
    with initialize_config_dir(config_dir=CONFIGS, version_base=None):
        return compose(config_name="config", overrides=list(overrides))


@pytest.fixture
def cfg():
    return load()


@pytest.fixture
def engagement(cfg):
    from pequod.types import Engagement

    return Engagement.model_validate(OmegaConf.to_container(cfg.engagement))


# --- fake model for agent tests ---

import uuid

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage


class FakeModel(GenericFakeChatModel):
    """Scripted replies. Records the tool names bound and the messages received."""

    bound: list = []
    seen: list = []

    def bind_tools(self, tools, **kwargs):
        self.bound = [getattr(t, "name", None) or t["function"]["name"] for t in tools]
        return self

    def _generate(self, messages, *args, **kwargs):
        self.seen.append(list(messages))
        return super()._generate(messages, *args, **kwargs)


def call(tool, /, **args):
    """An AI message with one tool call."""
    return AIMessage(content="", tool_calls=[{"name": tool, "args": args, "id": uuid.uuid4().hex}])


def fake(*messages):
    return FakeModel(messages=iter(messages), bound=[], seen=[])


# --- shared objects for agent tests ---

from datetime import datetime, timezone

NOW = datetime(2026, 11, 16, 8, 0, tzinfo=timezone.utc)
READ = {"graph_summary", "find_nodes", "neighbors"}
WRITE = {"add_node", "add_edge", "update_node"}
ANGLE = "Lean on clarity."


def wave(channel="email", intent="open_door", hour=10):
    return {
        "intent": intent,
        "strategy": "plain_message",
        "channel": channel,
        "send_at": f"2026-11-16T{hour:02d}:00:00+01:00",
    }


def path(*waves, subgoal="Learn which reports are slow"):
    return {"subgoals": [subgoal, "Find the cause"], "rationale": "Start from the stated symptom", "waves": list(waves)}


def interaction(channel="email", body="Hi Alex, which report is slowest?"):
    return {"channel": channel, "send_at": "2026-11-16T10:00:00+01:00", "body": body}


@pytest.fixture
def graph(engagement):
    from pequod.graph import KnowledgeGraph

    return KnowledgeGraph.from_engagement(engagement)


@pytest.fixture
def catalog(cfg):
    from pequod.strategies import StrategyCatalog

    return StrategyCatalog.from_config(cfg.strategies)


@pytest.fixture
def rules(cfg):
    from pequod.types import ChannelRules

    return {name: ChannelRules.model_validate(dict(c.rules)) for name, c in cfg.channels.items()}
