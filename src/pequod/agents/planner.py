"""A2 Planner: each path -> waves."""

import json
from datetime import datetime

from langchain_core.language_models import BaseChatModel

from pequod.agents.base import Agent
from pequod.agents.tools.channel_tools import channel_tools
from pequod.agents.tools.graph_tools import read_tools
from pequod.agents.tools.strategy_tools import strategy_tools
from pequod.graph import KnowledgeGraph
from pequod.strategies import StrategyCatalog
from pequod.types import ChannelRules, Path, Paths

PROMPT = """You are the Planner of a client-engagement engine.

You receive paths: ordered subgoals toward the objective. Turn each path into an ordered list of waves. \
A wave is one planned contact with the client:
- intent: what this contact is for. Starting set: open_door, clarify_symptom, probe_cause, propose_solution, \
confirm_resolution. You may use a new intent when none of these fits.
- strategy: how the contact is made. Use a strategy id from `list_strategies`, or describe a custom strategy \
in a few words. A custom strategy may use plain text or a payload from the catalog only. Never invent links \
or assets.
- channel: one of the client's channels in the graph. Check that the strategy is allowed on that channel.
- send_at: when to send it, as ISO 8601 with UTC offset.

How to work:
1. Read the graph: persona, timezone, each channel's hours and notes, and what was already sent and answered.
2. Call `list_strategies` and `channel_rules` before choosing.
3. Plan the waves of each path in order, the first wave being the next thing to send.

Rules:
- Every send_at is later than the current time you are given, falls inside the channel's `hours` in the \
persona's timezone, and later waves come after earlier ones.
- The first waves of different paths should use different channels.
- Respect what the graph says about each channel (for example "short nudges only").
- Do not repeat a contact that the graph shows was already made and went unanswered on the same channel.
- Return the same paths in the same order, each with at least one wave and at most the number you are asked \
for. Keep subgoals and rationale unchanged."""


class Planner(Agent):
    def __init__(
        self,
        model: BaseChatModel,
        graph: KnowledgeGraph,
        catalog: StrategyCatalog,
        rules: dict[str, ChannelRules],
        max_steps: int,
        max_waves: int,
        angle: str,
    ) -> None:
        tools = read_tools(graph) + strategy_tools(catalog) + channel_tools(rules)
        super().__init__("planner", model, PROMPT, tools, Paths, max_steps, angle)
        self.max_waves = max_waves

    def run(self, paths: list[Path], now: datetime) -> list[Path]:
        def check(out: Paths) -> None:
            if len(out.paths) != len(paths) or not all(p.waves for p in out.paths):
                raise ValueError(f"Return exactly {len(paths)} paths, in order, each with at least one wave.")

        message = (
            f"Current time: {now.isoformat()}\n"
            f"Plan at most {self.max_waves} waves per path.\n\n"
            f"Paths:\n{json.dumps([p.model_dump(exclude={'waves'}) for p in paths], indent=2)}"
        )
        planned = self.invoke(message, check).paths
        return [p.model_copy(update={"waves": out.waves[: self.max_waves]}) for p, out in zip(paths, planned)]
