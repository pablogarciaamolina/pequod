"""All Pydantic data classes."""

from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, BaseModel, Field


# --- engagement input and config ---

class Persona(BaseModel):
    name: str
    features: dict[str, str] = {}


class ChannelSpec(BaseModel):
    address: str
    features: dict[str, str] = {}


class Engagement(BaseModel):
    objective: str
    persona: Persona
    channels: dict[str, ChannelSpec] = Field(min_length=1)


class ChannelRules(BaseModel):
    max_length: int
    subject: bool
    links_ok: bool


class Strategy(BaseModel):
    description: str
    channels: list[str]
    payload: dict[str, str] | None = None


class ModelSpec(BaseModel):
    provider: str
    name: str
    params: dict[str, Any] = {}  # passed to the provider's chat model (temperature, base_url, ...)


# --- data moving between agents and loop ---

SendAt = Annotated[AwareDatetime, Field(description="ISO 8601 with UTC offset, e.g. 2026-11-16T10:00:00+01:00")]


class Wave(BaseModel):
    """One planned step of a path."""

    intent: str
    strategy: str  # catalog id or custom description
    channel: str
    send_at: SendAt


class Path(BaseModel):
    """Subgoals toward the objective (Strategist); waves are added by the Planner."""

    subgoals: list[str]
    rationale: str
    waves: list[Wave] = []


class Interaction(BaseModel):
    """One message to the persona on one channel."""

    channel: str
    send_at: SendAt
    body: str
    subject: str | None = None
    payload: dict[str, str] | None = None


class Reply(BaseModel):
    id: str
    channel: str
    body: str
    received_at: AwareDatetime


class StopSignal(BaseModel):
    """Whether the engagement should stop, judged from the persona's replies."""

    objective_met: bool = False
    solution_accepted: bool = False
    opt_out: bool = False
    evidence: str = Field("", description="The persona's exact words that justify a true flag; empty if none")

    @property
    def stop(self) -> bool:
        return self.objective_met or self.solution_accepted or self.opt_out


StopReason = Literal["objective_met", "solution_accepted", "opt_out", "max_iterations", "operator_stop"]


class Resolution(BaseModel):
    """Final report for the supervisor, who contacts the persona. Nothing is sent to the persona."""

    report: str


# --- trace ---

class Message(BaseModel):
    """One message of a conversation, in full: sent by the engine ("out") or received from the persona ("in")."""

    direction: Literal["out", "in"]
    channel: str
    at: AwareDatetime
    body: str
    subject: str | None = None
    payload: dict[str, str] | None = None


class SentLine(BaseModel):
    channel: str
    send_at: AwareDatetime  # when it really went out
    text: str  # first 80 characters of the body
    cut: bool  # True when the body was longer


class Status(BaseModel):
    """What the engine is doing right now (status.json)."""

    phase: str  # updating, planning, writing, waiting, reporting, finished, failed
    wave: int = 0
    max_iterations: int = 0
    pending: list[SentLine] = []  # planned for this wave, while waiting
    error: str = ""


class WaveRecord(BaseModel):
    """One line of trace.jsonl: what one wave planned, sent and learned."""

    wave: int
    snapshot: str  # file name of the graph this wave was planned from
    paths: list[str]  # "<rationale> -> <intent> on <channel>"
    interactions: list[SentLine]
    replies: list[Reply]  # absorbed by the update that closed this wave
    stop_signal: StopSignal
    reason: StopReason | None = None  # why the loop stopped after this wave; None = it continued


class AgentRun(BaseModel):
    """One line of agents.jsonl: one run of one agent, from its prompt to its answer or its error."""

    agent: str
    messages: list[dict]  # in order: type, content, and for a model turn its reasoning and tool calls
    error: str = ""  # why the run gave no valid output


# --- agent outputs that wrap a list ---

class Paths(BaseModel):
    """The paths toward the objective."""

    paths: list[Path] = Field(min_length=1)


class Review(BaseModel):
    """The final interactions after review, plus notes on what changed."""

    interactions: list[Interaction]
    notes: str = Field(description="One line per edit, or 'no changes'")
