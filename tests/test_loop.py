import json

import pytest
from conftest import ANGLE, NOW, Clock, FakeOperator, call, fake, interaction, path, wave

from pequod.agents.base import AgentError
from pequod.agents.composer import Composer
from pequod.agents.planner import Planner
from pequod.agents.resolver import Resolver
from pequod.agents.reviewer import Reviewer
from pequod.agents.strategist import Strategist
from pequod.agents.updater import Updater
from pequod.channels import build_channels
from pequod.channels.mock_hub import MockHub
from pequod.engagement import Agents, EngagementLoop, Scheduler
from pequod.trace import Trace

CAUSE = "the sync only runs at night"

# one iteration of scripted answers: two paths, first waves on email and whatsapp
STRATEGIST = call("Paths", paths=[path(), path(subgoal="Ask what they tried")])
PLANNER = call("Paths", paths=[path(wave("email")), path(wave("whatsapp"), subgoal="Ask what they tried")])
COMPOSER = [call("Interaction", **interaction("email")), call("Interaction", **interaction("whatsapp"))]
REVIEWER = call("Review", interactions=[interaction("email"), interaction("whatsapp")], notes="no changes")
RESOLVER = call("Resolution", report="THE REPORT")


def signal(**flags):
    return call("StopSignal", **flags)


class World:
    """A loop on fake models, a real hub in a temp folder, a fake clock and a scripted operator."""

    def __init__(self, tmp_path, cfg, graph, catalog, rules, updater, operator=(), iterations=1, max_iterations=5, planner=None):
        self.clock = Clock()
        self.hub = MockHub(tmp_path / "hub.db")
        self.operator = FakeOperator(self.clock, operator)
        channels = build_channels(cfg.channels, list(rules), self.hub, self.clock)
        self.models = {
            "strategist": fake(*[STRATEGIST] * iterations),
            "planner": fake(*(planner or [PLANNER] * iterations)),
            "composer": fake(*COMPOSER * iterations),
            "reviewer": fake(*[REVIEWER] * iterations),
            "updater": fake(*updater),
            "resolver": fake(RESOLVER),
        }
        m = self.models
        agents = Agents(
            strategist=Strategist(m["strategist"], graph, 4, 2),
            planner=Planner(m["planner"], graph, catalog, rules, 4, 3, ANGLE),
            composer=Composer(m["composer"], graph, catalog, rules, 4, ANGLE),
            reviewer=Reviewer(m["reviewer"], graph, rules, 4, ANGLE),
            updater=Updater(m["updater"], graph, 8),
            resolver=Resolver(m["resolver"], graph, 4, ANGLE),
        )
        self.trace = Trace(tmp_path / "run")
        scheduler = Scheduler(channels, self.operator, 24, self.clock, on_send=self.trace.sent)
        self.loop = EngagementLoop(
            "Find the problem", agents, channels, scheduler, max_iterations, self.clock, graph, self.trace
        )

    def reply(self, channel, body):
        return lambda: self.hub.add_reply(channel, body, self.clock.now)

    def files(self):
        return sorted(f.name for f in self.trace.folder.iterdir())

    def nodes(self, n):
        data = json.loads((self.trace.folder / f"graph_{n}.json").read_text(encoding="utf-8"))
        return [node["id"] for node in data["nodes"]]

    def said_to(self, agent):
        """The user messages an agent's model received, one per agent run."""
        return [messages[1].content for messages in self.models[agent].seen if len(messages) == 2]


@pytest.fixture
def world(tmp_path, cfg, graph, catalog, rules):
    return lambda **kwargs: World(tmp_path, cfg, graph, catalog, rules, **kwargs)


def test_engaged_branch(world):
    w = world(updater=[signal(root_problem_stated=True, evidence=CAUSE)])
    w.operator.script = [w.reply("whatsapp", CAUSE)]
    state = w.loop.run()
    assert state["reason"] == "root_problem_stated" and state["iteration"] == 1
    assert state["resolution"].report == "THE REPORT"
    assert [m["channel"] for m in w.hub.sent()] == ["email", "whatsapp"]
    assert "root_problem_stated" in w.said_to("resolver")[0] and CAUSE in w.said_to("resolver")[0]
    assert CAUSE in w.said_to("updater")[0]


def test_resistant_branch_ends_at_max_iterations(world):
    w = world(updater=[signal(), signal()], iterations=2, max_iterations=2)
    state = w.loop.run()
    assert state["reason"] == "max_iterations" and state["iteration"] == 2
    assert len(w.hub.sent()) == 4
    assert "max_iterations" in w.said_to("resolver")[0]


def test_opt_out_wins(world):
    w = world(updater=[signal(opt_out=True, root_problem_stated=True, evidence="stop")])
    assert w.loop.run()["reason"] == "opt_out"


def test_solution_accepted(world):
    w = world(updater=[signal(solution_accepted=True, evidence="ok, do it")])
    assert w.loop.run()["reason"] == "solution_accepted"


def test_operator_stop_still_updates(world):
    w = world(updater=[signal()], operator=["send", "stop"])
    state = w.loop.run()
    assert state["reason"] == "operator_stop" and state["iteration"] == 1
    assert "which report is slowest" in w.said_to("updater")[0]


def test_stop_before_anything_was_sent_makes_no_updater_call(world):
    w = world(updater=[], operator=["stop"])
    assert w.loop.run()["reason"] == "operator_stop"
    assert w.models["updater"].seen == []


def test_late_reply_is_processed_once(world):
    w = world(updater=[signal(), signal(), signal()], iterations=3, max_iterations=3)
    w.operator.script = [None, None, w.reply("sms", "late answer")]  # written during iteration 2's wait
    w.loop.run()
    updates = w.said_to("updater")
    assert len(updates) == 3
    assert ["late answer" in u for u in updates] == [False, True, False]


def test_second_composer_gets_the_taken_channel(world):
    w = world(updater=[signal()], max_iterations=1)
    w.loop.run()
    first, second = w.said_to("composer")
    assert "already taken by other paths: none" in first
    assert "already taken by other paths: email" in second


def test_enter_before_the_send_gives_the_updater_an_empty_sent_list(world):
    w = world(updater=[signal()], max_iterations=1)
    w.operator.script = [w.reply("sms", "who is this?"), "ok"]  # Enter before the send: everything is dropped
    state = w.loop.run()
    assert state["reason"] == "max_iterations" and state["iteration"] == 1 and w.hub.sent() == []
    update = w.said_to("updater")[0]
    assert "Messages we sent:\n[]" in update and "who is this?" in update


def test_updater_gets_the_real_send_time(world):
    w = world(updater=[signal()], operator=["send", "ok"], max_iterations=1)
    w.loop.run()
    assert NOW.isoformat().replace("+00:00", "Z") in w.said_to("updater")[0]


def test_planner_and_reviewer_get_the_current_time(world):
    w = world(updater=[signal()], max_iterations=1)
    w.loop.run()
    assert NOW.isoformat() in w.said_to("planner")[0] and NOW.isoformat() in w.said_to("reviewer")[0]


def test_agent_failure_stops_the_run(world):
    from langchain_core.messages import AIMessage

    w = world(updater=[], planner=[AIMessage("I would rather chat.") for _ in range(4)])
    with pytest.raises(AgentError, match="planner: no valid Paths after 4 model calls"):
        w.loop.run()
    assert w.hub.sent() == []


def test_more_iterations_than_the_default_graph_limit(world):
    w = world(updater=[signal()] * 8, iterations=8, max_iterations=8)
    assert w.loop.run()["iteration"] == 8


# --- trace, snapshots and report (Stage 4) ---


def test_engaged_run_leaves_trace_snapshots_and_report(world):
    w = world(updater=[signal(root_problem_stated=True, evidence=CAUSE)])
    w.operator.script = [w.reply("whatsapp", CAUSE)]
    w.loop.run()
    assert w.files() == ["graph_0.json", "graph_1.json", "messages.jsonl", "report.md", "status.json", "trace.jsonl"]
    (record,) = w.trace.records()
    assert (record.wave, record.snapshot, record.reason) == (1, "graph_0.json", "root_problem_stated")
    assert [i.channel for i in record.interactions] == ["email", "whatsapp"]
    assert [r.body for r in record.replies] == [CAUSE]
    assert record.stop_signal.root_problem_stated and record.stop_signal.evidence == CAUSE
    assert len(record.paths) == 2 and "on email" in record.paths[0]
    report = (w.trace.folder / "report.md").read_text(encoding="utf-8")
    assert report.startswith("Stop reason: root_problem_stated") and "THE REPORT" in report


def test_each_wave_gets_a_line_and_a_snapshot(world):
    w = world(updater=[signal(), signal()], iterations=2, max_iterations=2)
    w.loop.run()
    assert w.files() == ["graph_0.json", "graph_1.json", "graph_2.json", "messages.jsonl", "report.md", "status.json", "trace.jsonl"]
    assert [(r.wave, r.snapshot, r.reason) for r in w.trace.records()] == [
        (1, "graph_0.json", None),
        (2, "graph_1.json", "max_iterations"),
    ]


def test_snapshot_shows_what_the_updater_wrote(world):
    w = world(updater=[call("add_node", kind="fact", name="Nightly sync", attrs={}), signal()], max_iterations=1)
    w.loop.run()
    assert "nightly_sync" not in w.nodes(0) and "nightly_sync" in w.nodes(1)


def test_late_reply_is_in_the_line_of_the_update_that_absorbed_it(world):
    w = world(updater=[signal(), signal(), signal()], iterations=3, max_iterations=3)
    w.operator.script = [None, None, w.reply("sms", "late answer")]  # written during wave 2's wait
    w.loop.run()
    assert [[r.body for r in record.replies] for record in w.trace.records()] == [[], ["late answer"], []]


def test_trace_line_has_the_real_send_time(world):
    w = world(updater=[signal()], operator=["send", "ok"], max_iterations=1)
    w.loop.run()
    assert [i.send_at for i in w.trace.records()[0].interactions] == [NOW, NOW]


def test_stop_before_any_send_leaves_one_line_without_interactions(world):
    w = world(updater=[], operator=["stop"])
    w.loop.run()
    (record,) = w.trace.records()
    assert record.interactions == [] and record.reason == "operator_stop" and len(record.paths) == 2
    assert "report.md" in w.files()


def test_trace_survives_a_crash(world):
    from langchain_core.messages import AIMessage

    planner = [PLANNER, *[AIMessage("I would rather chat.") for _ in range(4)]]
    w = world(updater=[signal()], iterations=2, planner=planner)
    with pytest.raises(AgentError, match="planner"):
        w.loop.run()
    assert w.files() == ["graph_0.json", "graph_1.json", "messages.jsonl", "status.json", "trace.jsonl"]
    assert [r.wave for r in w.trace.records()] == [1]
    text = w.trace.explain()
    assert "Wave 1" in text and "Wave 2" not in text and "No report" in text


# --- status and message register (Stage 5) ---


def test_loop_reports_its_phases(world, monkeypatch):
    w = world(updater=[signal()], max_iterations=1)
    phases = []
    real = w.trace.status
    monkeypatch.setattr(w.trace, "status", lambda phase, *a, **k: (phases.append(phase), real(phase, *a, **k)))
    w.loop.run()
    assert phases == ["updating", "planning", "writing", "waiting", "updating", "reporting", "finished"]
    status = w.trace.read_status()
    assert (status.phase, status.wave, status.max_iterations) == ("finished", 1, 1)


def test_waiting_status_lists_the_pending_messages(world):
    w = world(updater=[], operator=["stop"])
    seen = []
    w.operator.script = [lambda: seen.append(w.trace.read_status()), "stop"]
    w.loop.run()
    assert seen[0].phase == "waiting" and seen[0].wave == 1
    assert [p.channel for p in seen[0].pending] == ["email", "whatsapp"]


def test_run_registers_every_message_in_full(world):
    w = world(updater=[signal(root_problem_stated=True, evidence=CAUSE)])
    w.operator.script = [w.reply("whatsapp", CAUSE)]
    w.loop.run()
    assert [(m.direction, m.channel) for m in w.trace.messages()] == [("out", "email"), ("out", "whatsapp"), ("in", "whatsapp")]
    assert w.trace.messages()[-1].body == CAUSE


def test_messages_are_registered_even_if_the_updater_fails(world):
    from langchain_core.messages import AIMessage

    w = world(updater=[AIMessage("no idea") for _ in range(8)])
    w.operator.script = [w.reply("sms", "hello?")]
    with pytest.raises(AgentError, match="updater"):
        w.loop.run()
    assert [(m.direction, m.channel) for m in w.trace.messages()] == [("out", "email"), ("out", "whatsapp"), ("in", "sms")]
