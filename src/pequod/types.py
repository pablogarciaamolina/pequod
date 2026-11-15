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
    """One message to the client on one channel."""

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
    """Whether the engagement should stop, judged from the client's replies."""

    root_problem_stated: bool = False
    solution_accepted: bool = False
    opt_out: bool = False
    evidence: str = Field("", description="The client's exact words that justify a true flag; empty if none")

    @property
    def stop(self) -> bool:
        return self.root_problem_stated or self.solution_accepted or self.opt_out


StopReason = Literal["root_problem_stated", "solution_accepted", "opt_out", "max_iterations", "operator_stop"]


class Resolution(BaseModel):
    """Final report for the supervisor, who contacts the client. Nothing is sent to the client."""

    report: str


# --- trace ---

class Message(BaseModel):
    """One message of a conversation, in full: sent by the engine ("out") or received from the client ("in")."""

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


# --- agent outputs that wrap a list ---

class Paths(BaseModel):
    """The paths toward the objective."""

    paths: list[Path] = Field(min_length=1)


class Review(BaseModel):
    """The final interactions after review, plus notes on what changed."""

    interactions: list[Interaction]
    notes: str = Field(description="One line per edit, or 'no changes'")
