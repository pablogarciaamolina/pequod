"""A3 Composer: a path's first wave -> Interaction."""

from langchain_core.language_models import BaseChatModel

from pequod.agents.base import Agent, AgentError
from pequod.agents.tools.channel_tools import channel_tools
from pequod.agents.tools.graph_tools import read_tools
from pequod.agents.tools.strategy_tools import strategy_tools
from pequod.graph import KnowledgeGraph
from pequod.strategies import StrategyCatalog
from pequod.types import ChannelRules, Interaction, Path

PROMPT = """You are the Composer of a client-engagement engine.

You receive one wave (intent, strategy, channel, send_at) and the path it belongs to. Write the single \
message that carries out this wave.

How to work:
1. Read the graph: who the client is, their communication style, and what was already said on each channel.
2. Call `channel_rules` for the channel and `list_strategies` if the wave uses a catalog strategy.
3. Write the message.

Rules:
- Serve the wave's intent, and only that. One clear ask per message.
- Stay within the channel's maximum length. Set `subject` only when the channel has subjects. Put a link in \
the body only when the channel allows links.
- If the strategy has a payload in the catalog, copy it into `payload` exactly and mention it in the body. \
Never invent links, files or facts.
- Use only facts from the graph. Refer to earlier messages and replies when it helps the client see continuity.
- Match the persona's communication style.
- The client knows these messages come from an assistant monitored by a human. Do not pretend to be a person.
- Keep the wave's channel and send_at, unless the channel is listed as taken by another path: then pick \
another available channel, check with `list_strategies` that the strategy is allowed there, and adapt the \
message and send_at to that channel's rules and hours."""


class Composer(Agent):
    def __init__(
        self,
        model: BaseChatModel,
        graph: KnowledgeGraph,
        catalog: StrategyCatalog,
        rules: dict[str, ChannelRules],
        max_steps: int,
        angle: str,
    ) -> None:
        tools = read_tools(graph) + strategy_tools(catalog) + channel_tools(rules)
        super().__init__("composer", model, PROMPT, tools, Interaction, max_steps, angle)
        self.channels = list(rules)
        self.catalog = catalog

    def run(self, path: Path, taken: list[str]) -> Interaction:
        free = [c for c in self.channels if c not in taken]
        if not free:
            raise AgentError("composer: no free channel left for this path")

        def check(out: Interaction) -> None:
            if out.channel not in free:
                raise ValueError(f"Channel '{out.channel}' is not available. Use one of: {', '.join(free)}")
            allowed = [s.payload for s in self.catalog.for_channel(out.channel).values() if s.payload]
            if out.payload is not None and out.payload not in allowed:
                raise ValueError(f"payload must be empty or copied from the catalog for {out.channel}: {allowed}")

        message = (
            f"Wave to write:\n{path.waves[0].model_dump_json(indent=2)}\n\n"
            f"Path subgoals: {path.subgoals}\n"
            f"Path rationale: {path.rationale}\n\n"
            f"Channels already taken by other paths: {', '.join(taken) or 'none'}"
        )
        return self.invoke(message, check)
