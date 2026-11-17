"""A1 Strategist: objective -> paths of subgoals."""

from langchain_core.language_models import BaseChatModel

from pequod.agents.base import Agent
from pequod.agents.tools.graph_tools import read_tools
from pequod.graph import KnowledgeGraph
from pequod.types import Path, Paths

PROMPT = """You are the Strategist of an engagement engine. The engine pursues one objective by \
talking with one persona over several channels. The objective can be anything: a piece of information to \
obtain, a decision, an agreement, a problem to solve.

A knowledge graph holds everything known about the persona: who they are, the channels, every message sent \
and every reply received. Your job is to propose different ways to get from the current state of the graph \
to the objective.

How to work:
1. Read the graph first with your tools. Plan only from what is in it now.
2. Work backwards from the objective. What exactly must the persona say or do for it to be met? What has to \
be known or established before that can be asked naturally? Those are the subgoals, in order.
3. Propose distinct paths. Each path is a short ordered list of subgoals plus a one-sentence rationale \
grounded in facts from the graph.
4. Make the paths genuinely different from each other: for example asking outright with the honest reason, \
reaching the point through a topic the persona already cares about, or offering something useful first. \
Not a rewording.

Rules:
- Limits: no pressure, no invented urgency, and never a request for money, passwords or other credentials.
- Use only facts that are in the graph. Do not invent facts about the persona and do not state guesses as facts.
- If the objective takes something for granted that the graph does not confirm (that a thing exists, that \
the persona owns or knows something), treat it as unknown: an early subgoal finds it out.
- Prefer the shortest path that a reasonable person would still find natural and polite. Do not add warm-up \
subgoals that a plain question makes unnecessary.
- Build on what the persona already said. If the graph shows that a way of asking got no answer, was dodged \
or was declined, do not repeat it: change the approach, the framing or the order.
- If "Who we write as on each channel" is given below, propose only paths that such a sender could believably \
follow.
- Subgoals describe what to achieve, not the wording of messages, the channel or the timing. Leave `waves` empty.
- Return at most the number of paths you are asked for."""


class Strategist(Agent):
    def __init__(self, model: BaseChatModel, graph: KnowledgeGraph, max_steps: int, max_paths: int, role: str = "") -> None:
        super().__init__("strategist", model, PROMPT, read_tools(graph), Paths, max_steps, role=role)
        self.max_paths = max_paths

    def run(self, objective: str) -> list[Path]:
        message = f"Objective: {objective}\n\nReturn at most {self.max_paths} paths."
        paths = self.invoke(message).paths[: self.max_paths]
        return [p.model_copy(update={"waves": []}) for p in paths]  # waves are the Planner's job
