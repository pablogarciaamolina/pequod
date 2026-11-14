"""A1 Strategist: objective -> paths of subgoals."""

from langchain_core.language_models import BaseChatModel

from pequod.agents.base import Agent
from pequod.agents.tools.graph_tools import read_tools
from pequod.graph import KnowledgeGraph
from pequod.types import Path, Paths

PROMPT = """You are the Strategist of a client-engagement engine.

A knowledge graph holds everything known about one client: the persona, the channels, every message sent \
and every reply received. Your job is to propose different ways to get from the current state of the graph \
to the objective.

How to work:
1. Read the graph first with your tools. Plan only from what is in it now.
2. Propose distinct paths. Each path is a short ordered list of subgoals (what we need to learn or achieve, \
in order) plus a one-sentence rationale grounded in facts from the graph.
3. Make the paths genuinely different from each other: a different angle of approach, not a rewording.

Rules:
- Use only facts that are in the graph. Do not invent facts about the client and do not state guesses as facts.
- If the client has already answered something, build on it; do not ask for it again.
- Subgoals describe what to achieve, not the wording of messages, the channel or the timing. Leave `waves` empty.
- Return at most the number of paths you are asked for."""


class Strategist(Agent):
    def __init__(self, model: BaseChatModel, graph: KnowledgeGraph, max_steps: int, max_paths: int) -> None:
        super().__init__("strategist", model, PROMPT, read_tools(graph), Paths, max_steps)
        self.max_paths = max_paths

    def run(self, objective: str) -> list[Path]:
        message = f"Objective: {objective}\n\nReturn at most {self.max_paths} paths."
        paths = self.invoke(message).paths[: self.max_paths]
        return [p.model_copy(update={"waves": []}) for p in paths]  # waves are the Planner's job
