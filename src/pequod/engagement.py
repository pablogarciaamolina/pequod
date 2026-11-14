"""LangGraph wave loop + scheduler."""

import logging
import queue
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, TextIO, TypedDict

from langgraph.graph import END, START, StateGraph

from pequod.agents.composer import Composer
from pequod.agents.planner import Planner
from pequod.agents.resolver import Resolver
from pequod.agents.reviewer import Reviewer
from pequod.agents.strategist import Strategist
from pequod.agents.updater import Updater
from pequod.channels.base import Channel
from pequod.graph import KnowledgeGraph
from pequod.trace import Trace
from pequod.types import Interaction, Path, Resolution, StopReason, StopSignal

log = logging.getLogger(__name__)

Command = Literal["ok", "stop", "send"]
COMMANDS: dict[str, Command] = {"": "ok", "q": "stop", "s": "send"}
KEYS = "Enter = next iteration (unsent messages are dropped) | s + Enter = send pending now | q + Enter = stop"


class Operator:
    """The human supervisor at the keyboard. Lines are read on a background thread."""

    def __init__(self, stream: TextIO = sys.stdin) -> None:
        self.lines: queue.Queue[str] = queue.Queue()
        threading.Thread(target=self._read, args=(stream,), daemon=True).start()

    def _read(self, stream: TextIO) -> None:
        for line in stream:
            self.lines.put(line.strip().lower())

    def clear(self) -> None:
        """Forget lines typed before now, so a stray Enter during a slow step does not end the next wait."""
        while not self.lines.empty():
            log.info("Ignored a key typed while the engine was busy.")
            self.lines.get_nowait()

    def wait(self, seconds: float) -> Command | None:
        """The next command, or None when `seconds` pass without one. Unknown lines are ignored."""
        end = time.monotonic() + min(seconds, threading.TIMEOUT_MAX)  # a far-away send_at must not overflow
        while True:
            try:
                line = self.lines.get(timeout=max(0.0, end - time.monotonic()))
            except queue.Empty:
                return None
            if line in COMMANDS:
                return COMMANDS[line]


class Scheduler:
    """Sends each Interaction at its send_at, then waits for replies (design §7)."""

    def __init__(
        self, channels: dict[str, Channel], operator: Operator, reply_window_h: float, clock: Callable[[], datetime]
    ) -> None:
        self.channels = channels
        self.operator = operator
        self.window = timedelta(hours=reply_window_h)
        self.clock = clock

    def _send(self, interaction: Interaction) -> None:
        i = interaction
        self.channels[i.channel].send(i)
        subject = f"\n  Subject: {i.subject}" if i.subject else ""
        payload = f"\n  Payload: {i.payload}" if i.payload else ""
        log.info("SENT on %s:%s\n  %s%s", i.channel, subject, i.body, payload)

    def run(self, pending: list[Interaction]) -> tuple[list[Interaction], bool]:
        """Returns (what was sent, operator asked to stop). Ends when the reply window after the last
        send has passed, or on an operator command."""
        self.operator.clear()
        pending = sorted(pending, key=lambda i: i.send_at)
        sent: list[Interaction] = []
        last_send = None
        send_now = False
        while True:
            now = self.clock()
            while pending and (send_now or pending[0].send_at <= now):
                self._send(pending[0])
                sent.append(pending.pop(0).model_copy(update={"send_at": now}))  # when it really went out
                last_send = now
            if pending:
                until = pending[0].send_at
                log.info("Next send: %s at %s. %s", pending[0].channel, until.isoformat(), KEYS)
            elif last_send is None:
                return sent, False
            else:
                until = last_send + self.window
                if until <= now:
                    return sent, False
                log.info("Waiting for replies until %s. %s", until.isoformat(), KEYS)
            command = self.operator.wait((until - now).total_seconds())
            if command == "ok":
                return sent, False
            if command == "stop":
                return sent, True
            send_now = command == "send"


class LoopState(TypedDict):
    iteration: int
    paths: list[Path]
    pending: list[Interaction]  # reviewed, not sent yet
    sent: list[Interaction]  # sent in the last wait, not yet in the graph
    signal: StopSignal
    operator_stop: bool
    reason: StopReason | None
    resolution: Resolution | None


@dataclass
class Agents:
    strategist: Strategist
    planner: Planner
    composer: Composer
    reviewer: Reviewer
    updater: Updater
    resolver: Resolver


STOP_FLAGS = ("opt_out", "solution_accepted", "root_problem_stated")  # first true one is the stop reason


class EngagementLoop:
    """The wave loop (design §1): update -> stop? resolve : plan -> act -> wait -> update."""

    def __init__(
        self,
        objective: str,
        agents: Agents,
        channels: dict[str, Channel],
        scheduler: Scheduler,
        max_iterations: int,
        clock: Callable[[], datetime],
        graph: KnowledgeGraph,
        trace: Trace,
    ) -> None:
        self.objective = objective
        self.agents = agents
        self.channels = channels
        self.scheduler = scheduler
        self.max_iterations = max_iterations
        self.clock = clock
        self.graph = graph  # only snapshotted here; agents use it through their tools
        self.trace = trace

        g = StateGraph(LoopState)
        for name in ("update", "plan", "act", "wait", "resolve"):
            g.add_node(name, getattr(self, name))
        g.add_edge(START, "update")
        g.add_conditional_edges(
            "update", lambda state: "stop" if state["reason"] else "continue", {"continue": "plan", "stop": "resolve"}
        )
        g.add_edge("plan", "act")
        g.add_edge("act", "wait")
        g.add_edge("wait", "update")
        g.add_edge("resolve", END)
        self.flow = g.compile()

    def run(self) -> LoopState:
        self.started = self.clock()
        self.seen: set[str] = set()  # ids of replies already given to the Updater
        state = LoopState(
            iteration=0, paths=[], pending=[], sent=[], signal=StopSignal(),
            operator_stop=False, reason=None, resolution=None,
        )
        # every iteration is 4 graph steps; LangGraph's default limit is 25
        return self.flow.invoke(state, {"recursion_limit": 4 * self.max_iterations + 10})

    def update(self, state: LoopState) -> dict:
        """Absorb what came in: every reply since the start that was not processed yet, from any wave."""
        replies = [r for c in self.channels.values() for r in c.fetch_replies(self.started) if r.id not in self.seen]
        replies.sort(key=lambda r: r.received_at)
        self.seen.update(r.id for r in replies)
        for r in replies:
            log.info("REPLY on %s: %s", r.channel, r.body)
        signal = self.agents.updater.run(state["sent"], replies)
        reason = (
            next((flag for flag in STOP_FLAGS if getattr(signal, flag)), None)
            or ("operator_stop" if state["operator_stop"] else None)
            or ("max_iterations" if state["iteration"] >= self.max_iterations else None)
        )
        wave = state["iteration"]  # the wave this update closes; 0 = the start, nothing sent yet
        self.trace.snapshot(self.graph, wave)
        if wave:
            self.trace.record(wave, state["paths"], state["sent"], replies, signal, reason)
        return {"signal": signal, "reason": reason, "sent": []}

    def plan(self, state: LoopState) -> dict:
        iteration = state["iteration"] + 1
        log.info("=== Iteration %d of %d ===", iteration, self.max_iterations)
        paths = self.agents.planner.run(self.agents.strategist.run(self.objective), self.clock())
        for p in paths:
            log.info("PATH: %s | first wave: %s on %s", p.rationale, p.waves[0].intent, p.waves[0].channel)
        return {"iteration": iteration, "paths": paths}

    def act(self, state: LoopState) -> dict:
        drafts: list[Interaction] = []
        for path in state["paths"]:  # one after another: each Composer sees the channels already used
            drafts.append(self.agents.composer.run(path, [d.channel for d in drafts]))
        review = self.agents.reviewer.run(drafts, self.clock())
        log.info("REVIEW: %s", review.notes)
        return {"pending": review.interactions}

    def wait(self, state: LoopState) -> dict:
        sent, stop = self.scheduler.run(state["pending"])
        return {"sent": sent, "pending": [], "operator_stop": stop}

    def resolve(self, state: LoopState) -> dict:
        log.info("=== Stopped: %s ===", state["reason"])
        resolution = self.agents.resolver.run(state["reason"], state["signal"], self.objective)
        self.trace.report(state["reason"], resolution)
        log.info("REPORT FOR THE SUPERVISOR\n%s", resolution.report)
        log.info("Run folder: %s (cards: pequod explain <folder>)", self.trace.folder)
        return {"resolution": resolution}
