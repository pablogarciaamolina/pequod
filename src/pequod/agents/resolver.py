"""A6 Resolver: stop reason -> Resolution."""

from langchain_core.language_models import BaseChatModel

from pequod.agents.base import Agent
from pequod.agents.tools.graph_tools import read_tools
from pequod.graph import KnowledgeGraph
from pequod.types import Resolution, StopReason, StopSignal

PROMPT = """You are the Resolver of a client-engagement engine. The engagement has stopped. Write the final \
report for the human supervisor. The supervisor, not you, will contact the client, so nothing you write is \
sent to the client.

Read the whole graph first. Then write the report as plain text with these sections, in this order:

OUTCOME: one or two sentences. Why the engagement stopped and whether the objective was met.
WHAT WE LEARNED: the facts the client stated, each with the client's own words quoted. Separate symptoms \
from the underlying cause.
WHAT WE TRIED: per channel, what was sent and how the client reacted (answered, no reply, declined).
OPEN POINTS: what is still unknown or unconfirmed.
RECOMMENDED REPLY TO THE CLIENT: a draft the supervisor can send.

How the stop reason shapes the recommended reply:
- root_problem_stated: propose the fix for the underlying cause, as a recommendation the supervisor verifies.
- solution_accepted: confirm what was agreed and the next step.
- max_iterations or operator_stop: a short closing note that leaves the door open.
- opt_out: write "None: the client asked not to be contacted."

Rules:
- Use only facts from the graph. Do not invent facts, links or promises.
- The conversational angle applies only to the recommended reply.
- Be brief and concrete. The supervisor should be able to act after one read."""


class Resolver(Agent):
    def __init__(self, model: BaseChatModel, graph: KnowledgeGraph, max_steps: int, angle: str) -> None:
        super().__init__("resolver", model, PROMPT, read_tools(graph), Resolution, max_steps, angle)

    def run(self, reason: StopReason, signal: StopSignal, objective: str) -> Resolution:
        message = (
            f"Objective: {objective}\n"
            f"Stop reason: {reason}\n"
            f"Client's words behind the stop: {signal.evidence or 'none'}"
        )
        return self.invoke(message)
