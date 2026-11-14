"""One record per wave + explain."""

import json
import textwrap
from datetime import datetime, timezone
from pathlib import Path as FilePath

from pequod.graph import KnowledgeGraph
from pequod.types import Interaction, Path, Reply, Resolution, SentLine, StopReason, StopSignal, WaveRecord

CUT = 80  # characters of a message body kept in the trace
FLAGS = ("root_problem_stated", "solution_accepted", "opt_out")


def when(at: datetime) -> str:
    return at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


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
    """The record of one run in its folder: trace.jsonl, graph_<n>.json, report.md. All UTF-8."""

    def __init__(self, folder: str | FilePath) -> None:
        self.folder = FilePath(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.lines = self.folder / "trace.jsonl"

    def snapshot(self, graph: KnowledgeGraph, n: int) -> str:
        """Save the graph after update n (0 = after intake). Returns the file name."""
        name = f"graph_{n}.json"
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
            interactions=[
                SentLine(channel=i.channel, send_at=i.send_at, text=i.body[:CUT], cut=len(i.body) > CUT) for i in sent
            ],
            replies=replies,
            stop_signal=signal,
            reason=reason,
        )
        with self.lines.open("a", encoding="utf-8", newline="\n") as f:
            f.write(record.model_dump_json() + "\n")
        return record

    def report(self, reason: StopReason, resolution: Resolution) -> None:
        (self.folder / "report.md").write_text(f"Stop reason: {reason}\n\n{resolution.report}\n", encoding="utf-8")

    def records(self) -> list[WaveRecord]:
        if not self.lines.exists():
            return []
        # Split on "\n" only: splitlines() would also split on characters JSON leaves unescaped (U+2028...).
        # The text after the last "\n" is a line still being written (or cut off by a crash): ignored.
        lines = self.lines.read_text(encoding="utf-8").split("\n")[:-1]
        return [WaveRecord.model_validate_json(line) for line in lines]

    def explain(self) -> str:
        """One card per wave, then the outcome. Works on a finished run and on one still in progress."""
        report = self.folder / "report.md"
        if not (self.lines.exists() or report.exists() or (self.folder / "graph_0.json").exists()):
            raise FileNotFoundError(f"Not a run folder (no trace.jsonl, report.md or graph_0.json): {self.folder}")
        cards = [card(r) for r in self.records()] or ["No wave has finished yet."]
        outcome = (
            report.read_text(encoding="utf-8").strip()
            if report.exists()
            else "No report: the run is in progress or was stopped by an error."
        )
        return "\n\n".join([*cards, "Outcome\n" + textwrap.indent(outcome, "  ")])
