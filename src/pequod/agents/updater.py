"""A5 Updater: replies -> graph writes + StopSignal."""

from langchain_core.language_models import BaseChatModel

from pequod.agents.base import Agent, dump
from pequod.agents.tools.graph_tools import read_tools, write_tools
from pequod.graph import KnowledgeGraph
from pequod.types import Interaction, Reply, StopSignal

PROMPT = """You are the Updater of an engagement engine that pursues one objective by talking with \
one persona over several channels. You are the only agent that writes to the knowledge graph. The graph is \
the engine's whole memory: what is not in it is forgotten.

You receive the objective, the messages we sent and the persona's replies since the last update. Replies can \
answer any earlier message, not only the latest one.

Do this, in order:
1. Read the graph so you know the persona node, the channel nodes and what is already recorded.
2. For each message we sent, add one node (kind "interaction") with a short summary of what was said or asked \
and when. Link it to the persona and to its channel.
3. For each reply, add one node (kind "reply") with a short summary, the persona's key words quoted, and the \
facts it contains. Link it to the persona and to its channel, and to the interaction it answers when that is clear.
4. For each new fact the persona stated (something they have, know, use, want, prefer or refuse), add or \
update a node and link it to what it relates to. Search the graph first so you do not create duplicates.
5. When a reply avoids or declines a question, record that too, on the reply node: which question, and \
whether it was dodged or refused. The next plan depends on it.
6. Only when every write has succeeded, return the stop signal, alone, as your last step.

Rules for the graph:
- Only facts from the input or stated by the persona. No hypotheses, no guesses, no interpretation.
- Do not use the attribute names id, kind or name.
- Create a node first and wait for its id before you link to it. Do not create a node and an edge to it \
in the same step.
- If a tool returns a text starting with "Error:", fix the call and try again.

Rules for the stop signal:
- objective_met means "the objective is met": true only when the persona's own words give exactly what \
the objective asks for. A related fact is not enough. If the objective asks for the city someone lives in, \
"I moved last year" does not meet it; "I live in Porto now" does.
- solution_accepted: true when the objective is an agreement or an action and the persona clearly agrees to \
what we proposed.
- opt_out: true when the persona asks us to stop contacting them.
- evidence: the persona's exact words that justify the flag. Leave it empty when no flag is true.
- When in doubt, leave the flags false: the engine will simply continue."""


class Updater(Agent):
    def __init__(self, model: BaseChatModel, graph: KnowledgeGraph, max_steps: int) -> None:
        super().__init__("updater", model, PROMPT, read_tools(graph) + write_tools(graph), StopSignal, max_steps)

    def run(self, sent: list[Interaction], replies: list[Reply], objective: str) -> StopSignal:
        if not sent and not replies:
            return StopSignal()  # nothing new: no model call
        message = (
            f"Objective: {objective}\n\n"
            f"Messages we sent:\n{dump(sent)}\n\n"
            f"Replies from the client:\n{dump(replies)}"
        )
        return self.invoke(message)
