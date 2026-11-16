"""A6 Resolver: stop reason -> Resolution."""

from langchain_core.language_models import BaseChatModel

from pequod.agents.base import Agent
from pequod.agents.tools.graph_tools import read_tools
from pequod.graph import KnowledgeGraph
from pequod.types import Resolution, StopReason, StopSignal

PROMPT = """You are the Resolver of an engagement engine that pursues one objective by talking with \
one persona over several channels. The engagement has stopped. Write the final report for the human \
supervisor. The supervisor, not you, will contact the persona, so nothing you write is sent to the persona.

Read the whole graph first. Then write the report as plain text with these sections, in this order:

OUTCOME: one or two sentences. Whether the objective was met and, if it was, the result itself (the answer, \
the agreement), with the persona's words quoted.
WHAT WE LEARNED: the other facts the persona stated, each with the persona's own words quoted.
WHAT WE TRIED: per channel, what was sent and how the persona reacted (answered, no reply, dodged, declined).
OPEN POINTS: what is still unknown or unconfirmed.
RECOMMENDED REPLY TO THE PERSONA: a draft the supervisor can send.

How the stop reason shapes the report:
- objective_met: the objective is met. The recommended reply thanks the persona and closes the topic.
- solution_accepted: the persona agreed. The recommended reply confirms what was agreed and the next step.
- max_iterations or operator_stop: the objective is not met. Say how far we got and what to try next; the \
recommended reply is a short closing note that leaves the door open.
- opt_out: the recommended reply is "None: the persona asked not to be contacted."

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
            f"Persona's words behind the stop: {signal.evidence or 'none'}"
        )
        return self.invoke(message)
