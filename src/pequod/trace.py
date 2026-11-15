"""One record per wave + explain."""

import json
import logging
import os
import textwrap
import time
from datetime import datetime, timezone
from pathlib import Path as FilePath

from pequod.graph import KnowledgeGraph
from pequod.types import (
    Interaction, Message, Path, Reply, Resolution, SentLine, Status, StopReason, StopSignal, WaveRecord,
)

log = logging.getLogger(__name__)

CUT = 80  # characters of a message body kept in the trace
FLAGS = ("root_problem_stated", "solution_accepted", "opt_out")


def when(at: datetime) -> str:
    return at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def line(interaction: Interaction) -> SentLine:
    i = interaction
    return SentLine(channel=i.channel, send_at=i.send_at, text=i.body[:CUT], cut=len(i.body) > CUT)


def quoted(text: str) -> str:
    """Text on one line, in quotes: line breaks and quotes inside it are escaped."""
    return json.dumps(text, ensure_ascii=False)


def card(record: WaveRecord) -> str:
    """One wave as a short text card."""

    def section(title: str, items: list[str]) -> list[str]:
        return [f"  {title}", *([f"    - {item}" for item in items] or ["    (none)"])]

    signal = record.stop_signal
    flags = ", ".join(flag for flag in FLAGS if getattr(signal, flag)) or "none"
    evidence = f" · {quoted(signal.evidence)}" if signal.evidence else ""
    return "\n".join(
        [
            f"Wave {record.wave} · planned from {record.snapshot}",
            *section("Paths", record.paths),
            *section(
                "Sent",
                [f"{i.channel} {when(i.send_at)}: {quoted(i.text + ('…' if i.cut else ''))}" for i in record.interactions],
            ),
            *section("Replies absorbed", [f"{r.channel} {when(r.received_at)}: {quoted(r.body)}" for r in record.replies]),
            f"  Stop signal: {flags}{evidence}",
            f"  Decision: {f'stop ({record.reason})' if record.reason else 'continue'}",
        ]
    )


class Trace:
    """The record of one run in its folder, all UTF-8: trace.jsonl (one line per wave), messages.jsonl
    (every message in full), graph_<n>.json, status.json (what the engine is doing now), report.md."""

    def __init__(self, folder: str | FilePath, register: bool = True) -> None:
        """`register=False`: nothing of what was planned, said or learned is stored; only a status
        without message text, which the simulator needs."""
        self.register = register
        self.folder = FilePath(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.lines = self.folder / "trace.jsonl"

    def snapshot(self, graph: KnowledgeGraph, n: int) -> str:
        """Save the graph after update n (0 = after intake). Returns the file name."""
        name = f"graph_{n}.json"
        if self.register:
            graph.snapshot(self.folder / name)
        return name

    def record(
        self,
        wave: int,
        paths: list[Path],
        sent: list[Interaction],
        replies: list[Reply],
        signal: StopSignal,
        reason: StopReason | None,
    ) -> WaveRecord:
        """Append the line of one wave, once the update that closes it has finished."""
        record = WaveRecord(
            wave=wave,
            snapshot=f"graph_{wave - 1}.json",
            paths=[f"{p.rationale} -> {p.waves[0].intent} on {p.waves[0].channel}" for p in paths],
            interactions=[line(i) for i in sent],
            replies=replies,
            stop_signal=signal,
            reason=reason,
        )
        if self.register:
            self._append(self.lines, record)
        return record

    def report(self, reason: StopReason, resolution: Resolution) -> None:
        if self.register:
            self._replace("report.md", f"Stop reason: {reason}\n\n{resolution.report}\n")

    def read_report(self) -> str | None:
        report = self.folder / "report.md"
        return report.read_text(encoding="utf-8").strip() if report.exists() else None

    def records(self) -> list[WaveRecord]:
        return [WaveRecord.model_validate_json(text) for text in self._lines(self.lines)]

    # --- every message in full ---

    def sent(self, interaction: Interaction) -> None:
        """Register a message at the moment it goes out (`send_at` is the real time)."""
        i = interaction
        if self.register:
            self._append(
                self.folder / "messages.jsonl",
                Message(direction="out", channel=i.channel, at=i.send_at, body=i.body, subject=i.subject, payload=i.payload),
            )

    def received(self, reply: Reply) -> None:
        """Register a reply at the moment it is fetched."""
        if self.register:
            message = Message(direction="in", channel=reply.channel, at=reply.received_at, body=reply.body)
            self._append(self.folder / "messages.jsonl", message)

    def messages(self) -> list[Message]:
        return [Message.model_validate_json(text) for text in self._lines(self.folder / "messages.jsonl")]

    # --- what the engine is doing now ---

    def status(
        self, phase: str, wave: int = 0, max_iterations: int = 0, pending: list[Interaction] = (), error: str = ""
    ) -> None:
        lines = [line(i) for i in pending]
        if not self.register:
            lines = [item.model_copy(update={"text": "", "cut": False}) for item in lines]
        self._show(Status(phase=phase, wave=wave, max_iterations=max_iterations, pending=lines, error=error))

    def read_status(self) -> Status | None:
        status = self.folder / "status.json"
        return Status.model_validate_json(status.read_text(encoding="utf-8")) if status.exists() else None

    def fail(self, error: str) -> None:
        """Mark the run as stopped by an error, keeping the wave it was in."""
        if not self.register:  # an agent's error can quote a model's words: keep its first sentence only
            error = error.split(" Last message:")[0]
        last = self.read_status() or Status(phase="failed")
        self._show(last.model_copy(update={"phase": "failed", "pending": [], "error": error}))

    def _show(self, status: Status) -> None:
        try:
            self._replace("status.json", status.model_dump_json())
        except OSError as e:  # the status is only for display: never stop a run for it
            log.warning("Could not write the status (%s): %s", status.phase, e)

    # --- files ---

    @staticmethod
    def _append(path: FilePath, item) -> None:
        with path.open("a", encoding="utf-8", newline="\n") as f:
            f.write(item.model_dump_json() + "\n")

    @staticmethod
    def _lines(path: FilePath) -> list[str]:
        if not path.exists():
            return []
        # Split on "\n" only: splitlines() would also split on characters JSON leaves unescaped (U+2028...).
        # The text after the last "\n" is a line still being written (or cut off by a crash): ignored.
        return path.read_text(encoding="utf-8").split("\n")[:-1]

    def _replace(self, name: str, text: str) -> None:
        """Write a whole file through a temporary one, so a reader never sees half of it."""
        temporary = self.folder / (name + ".tmp")
        temporary.write_text(text, encoding="utf-8")
        for attempt in range(20):
            try:
                os.replace(temporary, self.folder / name)
                return
            except PermissionError:  # Windows: a reader has the file open at this moment
                if attempt == 19:
                    raise
                time.sleep(0.05)

    def explain(self) -> str:
        """One card per wave, then the outcome. Works on a finished run and on one still in progress."""
        report = self.folder / "report.md"
        if not (self.lines.exists() or report.exists() or (self.folder / "graph_0.json").exists()):
            raise FileNotFoundError(f"Not a run folder (no trace.jsonl, report.md or graph_0.json): {self.folder}")
        cards = [card(r) for r in self.records()] or ["No wave has finished yet."]
        outcome = self.read_report() or "No report: the run is in progress or was stopped by an error."
        return "\n\n".join([*cards, "Outcome\n" + textwrap.indent(outcome, "  ")])
