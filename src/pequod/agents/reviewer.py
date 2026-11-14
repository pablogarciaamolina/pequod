"""A4 Reviewer: draft Interactions -> final Interactions."""

from datetime import datetime

from langchain_core.language_models import BaseChatModel

from pequod.agents.base import Agent, dump, fits
from pequod.agents.tools.channel_tools import channel_tools
from pequod.agents.tools.graph_tools import read_tools
from pequod.graph import KnowledgeGraph
from pequod.types import ChannelRules, Interaction, Review

PROMPT = """You are the Reviewer of a client-engagement engine.

You receive the draft messages that will go out together, one per channel. The client will see all of them. \
Polish them and return the final versions. You edit; you never block.

Check each draft for:
- Angle and tone: it follows the conversational angle and the persona's communication style.
- Facts: every statement about the client or about earlier messages is in the graph. Remove anything that is not.
- Channel rules: length and subject, using `channel_rules`.
- Timing: send_at is later than the current time and inside the channel's hours in the persona's timezone.
- The set as a whole: the messages do not repeat each other word for word and do not contradict each other.

Rules:
- You may change body, subject and send_at. Leave payload as it is.
- Return the same number of interactions, in the same order, on the same channels. Never drop, add or move one.
- If a draft is already good, return it unchanged.
- In `notes`, write one line per edit you made and why, or "no changes"."""


class Reviewer(Agent):
    def __init__(
        self,
        model: BaseChatModel,
        graph: KnowledgeGraph,
        rules: dict[str, ChannelRules],
        max_steps: int,
        angle: str,
    ) -> None:
        tools = read_tools(graph) + channel_tools(rules)
        super().__init__("reviewer", model, PROMPT, tools, Review, max_steps, angle)
        self.rules = rules

    def run(self, drafts: list[Interaction], now: datetime) -> Review:
        channels = [d.channel for d in drafts]

        def check(out: Review) -> None:
            if [i.channel for i in out.interactions] != channels:
                raise ValueError(f"Keep the same interactions and channels, in order: {', '.join(channels)}")
            if [i.payload for i in out.interactions] != [d.payload for d in drafts]:
                raise ValueError("Leave every payload exactly as it is in the drafts.")
            for i in out.interactions:
                fits(i, self.rules[i.channel])

        message = (
            f"Current time: {now.isoformat()}\n\n"
            f"Drafts:\n{dump(drafts)}"
        )
        return self.invoke(message, check)
