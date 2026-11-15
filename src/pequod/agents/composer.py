"""A3 Composer: a path's first wave -> Interaction."""

from langchain_core.language_models import BaseChatModel

from pequod.agents.base import Agent, AgentError, fits
from pequod.agents.tools.channel_tools import channel_tools
from pequod.agents.tools.graph_tools import read_tools
from pequod.agents.tools.strategy_tools import strategy_tools
from pequod.graph import KnowledgeGraph
from pequod.strategies import StrategyCatalog
from pequod.types import ChannelRules, Interaction, Path

PROMPT = """You are the Composer of an engagement engine that pursues one objective by talking with \
one persona over several channels.

You receive one wave (intent, strategy, channel, send_at) and the path it belongs to. Write the single \
message that carries out this wave.

How to work:
1. Read the graph: who the persona is, their communication style, and what was already said on each channel.
2. Call `channel_rules` for the channel and `list_strategies` if the wave uses a catalog strategy.
3. Write the message.

Rules:
- Serve the wave's intent, and only that. One clear ask per message, never two questions.
- Make it easy to answer: the persona should be able to reply in one line without looking anything up.
- Sound like a considerate person writing to this particular persona, not like a form. No filler, no flattery.
- When the ask is personal or unexpected, say in a few words why we ask, in a way that fits the role, or make \
clear that answering is optional.
- If the persona already replied, react to what they said before asking the next thing.
- Stay within the channel's maximum length. Set `subject` only when the channel has subjects. Put a link in \
the body only when the channel allows links.
- If the strategy has a payload in the catalog, copy it into `payload` exactly and mention it in the body. \
Never invent links, files or facts.
- Use only facts from the graph. Do not write as if we knew something the graph does not confirm.
- Match the persona's communication style.
- If "Who we write as on each channel" below names a role for the message's channel, write as that role: its \
name, its voice and its reason for writing. Do not add titles, affiliations or claims that the role text does \
not state. On a channel without a role, write as an assistant monitored by a human and do not pretend to be a person.
- Limits: no pressure, no invented urgency, and never a request for money, passwords or other credentials.
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
        role: str = "",
    ) -> None:
        tools = read_tools(graph) + strategy_tools(catalog) + channel_tools(rules)
        super().__init__("composer", model, PROMPT, tools, Interaction, max_steps, angle, role)
        self.rules = rules
        self.catalog = catalog

    def run(self, path: Path, taken: list[str]) -> Interaction:
        free = [c for c in self.rules if c not in taken]
        if not free:
            raise AgentError("composer: no free channel left for this path")

        def check(out: Interaction) -> None:
            if out.channel not in free:
                raise ValueError(f"Channel '{out.channel}' is not available. Use one of: {', '.join(free)}")
            allowed = [s.payload for s in self.catalog.for_channel(out.channel).values() if s.payload]
            if out.payload is not None and out.payload not in allowed:
                raise ValueError(f"payload must be empty or copied from the catalog for {out.channel}: {allowed}")
            fits(out, self.rules[out.channel])

        message = (
            f"Wave to write:\n{path.waves[0].model_dump_json(indent=2)}\n\n"
            f"Path subgoals: {path.subgoals}\n"
            f"Path rationale: {path.rationale}\n\n"
            f"Channels already taken by other paths: {', '.join(taken) or 'none'}"
        )
        return self.invoke(message, check)
