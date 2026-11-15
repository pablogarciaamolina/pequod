import json

import pytest
from conftest import NOW, interaction, path, wave

from pequod.trace import Trace
from pequod.types import Interaction, Path, Reply, Resolution, StopSignal, WaveRecord

PATHS = [Path(**path(wave("email", "open_door")))]
SENT = [Interaction(**interaction("email"))]
REPLIES = [Reply(id="whatsapp-2", channel="whatsapp", body="Our stock numbers are a day old", received_at=NOW)]
SIGNAL = StopSignal(objective_met=True, evidence="a day old")


@pytest.fixture
def trace(tmp_path):
    return Trace(tmp_path / "run")


def lines(trace):
    return (trace.folder / "trace.jsonl").read_text(encoding="utf-8").splitlines()


def test_snapshot_writes_the_graph(trace, graph):
    assert trace.snapshot(graph, 0) == "graph_0.json"
    data = json.loads((trace.folder / "graph_0.json").read_text(encoding="utf-8"))
    assert "alex_carter" in [n["id"] for n in data["nodes"]]


def test_record_appends_one_json_line_per_wave(trace):
    first = trace.record(1, PATHS, SENT, REPLIES, StopSignal(), None)
    second = trace.record(2, PATHS, [], [], SIGNAL, "objective_met")
    assert len(lines(trace)) == 2 and trace.records() == [first, second]
    assert [(r.wave, r.snapshot, r.reason) for r in trace.records()] == [
        (1, "graph_0.json", None),
        (2, "graph_1.json", "objective_met"),
    ]
    assert type(first) is WaveRecord and first.replies == REPLIES and second.stop_signal == SIGNAL


def test_record_cuts_the_body_at_80_characters(trace):
    long = Interaction(**interaction("email", "x" * 200))
    record = trace.record(1, PATHS, [long, SENT[0]], [], StopSignal(), None)
    cut, short = record.interactions
    assert (len(cut.text), cut.cut) == (80, True)
    assert (short.text, short.cut) == (SENT[0].body, False)
    assert (short.channel, short.send_at) == ("email", SENT[0].send_at)


def test_record_keeps_line_breaks_and_non_ascii_on_one_line(trace):
    body = 'Hallo Alex,\n"Grüße" 👍'
    reply = Reply(id="sms-1", channel="sms", body=body, received_at=NOW)
    trace.record(1, PATHS, [Interaction(**interaction("email", body))], [reply], StopSignal(evidence=body), None)
    assert len(lines(trace)) == 1
    record = trace.records()[0]
    assert record.interactions[0].text == record.replies[0].body == record.stop_signal.evidence == body


def test_path_line_names_rationale_intent_and_channel(trace):
    record = trace.record(1, PATHS, [], [], StopSignal(), None)
    assert record.paths == ["Start from the stated symptom -> open_door on email"]


def test_report_starts_with_the_reason(trace):
    trace.report("opt_out", Resolution(report="OUTCOME: stopped.\nGrüße 👍"))
    text = (trace.folder / "report.md").read_text(encoding="utf-8")
    assert text.startswith("Stop reason: opt_out\n") and "OUTCOME: stopped.\nGrüße 👍" in text


def test_records_of_a_folder_without_trace_is_empty(trace):
    assert trace.records() == []


# --- explain ---

from datetime import timedelta

from pequod.types import Interaction as I

LONG = I(**interaction("email", "x" * 200))
CARD = """Wave 1 · planned from graph_0.json
  Paths
    - Start from the stated symptom -> open_door on email
  Sent
    - email 2026-11-16 09:00 UTC: "Hi Alex, which report is slowest?"
  Replies absorbed
    - whatsapp 2026-11-16 08:00 UTC: "Our stock numbers are a day old"
  Stop signal: objective_met · "a day old"
  Decision: stop (objective_met)"""


def test_card_shows_paths_sent_replies_signal_and_decision(trace):
    trace.record(1, PATHS, SENT, REPLIES, SIGNAL, "objective_met")
    assert trace.explain().startswith(CARD + "\n")


def test_empty_card(trace):
    trace.record(1, [], [], [], StopSignal(), None)
    text = trace.explain()
    assert "  Paths\n    (none)\n  Sent\n    (none)\n  Replies absorbed\n    (none)\n" in text
    assert "  Stop signal: none\n  Decision: continue" in text


def test_cut_body_is_marked(trace):
    trace.record(1, PATHS, [LONG, SENT[0]], [], StopSignal(), None)
    text = trace.explain()
    assert '"' + "x" * 80 + '…"' in text and 'slowest?"' in text and 'slowest?…' not in text


def test_several_true_flags_are_all_named(trace):
    trace.record(1, PATHS, [], [], StopSignal(opt_out=True, objective_met=True, evidence="stop"), "opt_out")
    assert 'Stop signal: objective_met, opt_out · "stop"' in trace.explain()
    assert "Decision: stop (opt_out)" in trace.explain()


def test_explain_prints_one_card_per_wave_in_order(trace):
    trace.record(1, PATHS, SENT, [], StopSignal(), None)
    trace.record(2, PATHS, SENT, [], StopSignal(), "max_iterations")
    text = trace.explain()
    assert text.index("Wave 1 · planned from graph_0.json") < text.index("Wave 2 · planned from graph_1.json")


def test_explain_ends_with_the_report(trace):
    trace.record(1, PATHS, SENT, [], StopSignal(), "max_iterations")
    trace.report("max_iterations", Resolution(report="OUTCOME: nothing learned."))
    assert trace.explain().endswith("Outcome\n  Stop reason: max_iterations\n\n  OUTCOME: nothing learned.")


def test_explain_without_report_says_not_finished(trace):
    trace.record(1, PATHS, SENT, [], StopSignal(), None)
    assert trace.explain().endswith("Outcome\n  No report: the run is in progress or was stopped by an error.")


def test_explain_of_a_folder_that_is_not_a_run_raises(trace):
    with pytest.raises(FileNotFoundError, match="Not a run folder"):
        trace.explain()


def test_explain_before_the_first_wave_has_finished(trace, graph):
    trace.snapshot(graph, 0)  # the run has started; wave 1 is still being planned or waiting
    assert trace.explain().startswith("No wave has finished yet.\n\nOutcome\n  No report")


def test_explain_shows_the_report_of_a_run_that_stopped_before_any_wave(trace, graph):
    trace.snapshot(graph, 0)
    trace.report("max_iterations", Resolution(report="NOTHING DONE"))
    assert "No wave has finished yet." in trace.explain() and "NOTHING DONE" in trace.explain()


def test_times_are_shown_in_utc(trace):
    berlin = SENT[0].send_at  # 10:00+01:00
    assert berlin.utcoffset() == timedelta(hours=1)
    trace.record(1, PATHS, SENT, [], StopSignal(), None)
    assert "email 2026-11-16 09:00 UTC" in trace.explain()


@pytest.mark.parametrize("separator", ["\u2028", "\u2029", "\x85", "\x0c", "\r"])
def test_unicode_line_separators_in_a_reply_do_not_split_the_line(trace, separator):
    """str.splitlines() also splits on these; JSON does not escape the first three."""
    body = f"first{separator}second"
    trace.record(1, PATHS, [], [Reply(id="sms-1", channel="sms", body=body, received_at=NOW)], StopSignal(), None)
    assert trace.records()[0].replies[0].body == body
    assert "Wave 1" in trace.explain()


def test_a_half_written_last_line_is_ignored(trace):
    """The engine may be writing, or may have been killed, while someone reads."""
    trace.record(1, PATHS, SENT, [], StopSignal(), None)
    with trace.lines.open("a", encoding="utf-8") as f:
        f.write('{"wave": 2, "snap')
    assert [r.wave for r in trace.records()] == [1]
    assert "Wave 1" in trace.explain() and "Wave 2" not in trace.explain()


def test_trace_file_uses_plain_line_feeds(trace):
    trace.record(1, PATHS, SENT, [], StopSignal(), None)
    assert trace.lines.read_bytes().endswith(b"}\n") and b"\r" not in trace.lines.read_bytes()


def test_card_keeps_quotes_and_line_breaks_inside_one_line(trace):
    reply = Reply(id="sms-1", channel="sms", body='He said "no"\nline2', received_at=NOW)
    signal = StopSignal(opt_out=True, evidence='"stop"')
    trace.record(1, PATHS, [I(**interaction("email", "Hi,\nAlex"))], [reply], signal, "opt_out")
    card = trace.explain().split("\n\nOutcome")[0]
    assert len(card.splitlines()) == 9  # the fixed layout: no text spills onto extra lines
    assert r'"He said \"no\"\nline2"' in card and r'"Hi,\nAlex"' in card and r'· "\"stop\""' in card


# --- status and the message register (Stage 5) ---

from pequod.types import Message, Status


def test_read_status_without_file_is_none(trace):
    assert trace.read_status() is None


def test_status_round_trip(trace):
    trace.status("waiting", 2, 5, [LONG, SENT[0]])
    status = trace.read_status()
    assert type(status) is Status
    assert (status.phase, status.wave, status.max_iterations, status.error) == ("waiting", 2, 5, "")
    assert [(p.channel, len(p.text), p.cut) for p in status.pending] == [("email", 80, True), ("email", 33, False)]


def test_status_is_replaced_not_appended(trace):
    trace.status("planning", 1, 5)
    trace.status("writing", 1, 5)
    assert trace.read_status().phase == "writing"


def test_fail_without_an_earlier_status(trace):
    trace.fail("boom")
    assert (trace.read_status().phase, trace.read_status().error) == ("failed", "boom")


def test_no_temporary_file_is_left(trace):
    trace.status("planning", 1, 5)
    trace.report("opt_out", Resolution(report="R"))
    assert sorted(f.name for f in trace.folder.iterdir()) == ["report.md", "status.json"]


def test_read_report(trace):
    assert trace.read_report() is None
    trace.report("opt_out", Resolution(report="R"))
    assert trace.read_report() == "Stop reason: opt_out\n\nR"


def test_sent_and_received_are_registered_in_full(trace):
    long = I(**interaction("email", "x" * 200), subject="S", payload={"url": "https://kb.example/erp-sync"})
    trace.sent(long)
    trace.received(REPLIES[0])
    out, back = trace.messages()
    assert all(type(m) is Message for m in (out, back))
    assert (out.direction, out.channel, out.at, out.body, out.subject, out.payload) == (
        "out", "email", long.send_at, "x" * 200, "S", long.payload,
    )
    assert (back.direction, back.channel, back.at, back.body) == ("in", "whatsapp", NOW, REPLIES[0].body)
    assert (trace.folder / "messages.jsonl").read_bytes().count(b"\n") == 2


def test_messages_of_a_folder_without_register_is_empty(trace):
    assert trace.messages() == []


def test_fail_keeps_the_wave(trace):
    trace.status("planning", 2, 5)
    trace.fail("planner: no valid Paths")
    status = trace.read_status()
    assert (status.phase, status.wave, status.error) == ("failed", 2, "planner: no valid Paths")


def test_a_status_that_cannot_be_written_does_not_stop_the_run(trace, monkeypatch, caplog):
    """status.json is only for display."""
    import os

    def locked(*args):
        raise PermissionError("in use")

    monkeypatch.setattr(os, "replace", locked)
    monkeypatch.setattr("pequod.trace.time.sleep", lambda seconds: None)
    trace.status("planning", 1, 5)
    assert "status" in caplog.text
    with pytest.raises(PermissionError):  # the report must not be lost silently
        trace.report("opt_out", Resolution(report="R"))


# --- register off (Stage 6) ---


def test_register_off_writes_only_a_status_without_text(tmp_path, graph):
    trace = Trace(tmp_path / "run", register=False)
    assert trace.snapshot(graph, 0) == "graph_0.json"
    record = trace.record(1, PATHS, SENT, REPLIES, SIGNAL, "objective_met")
    trace.sent(SENT[0])
    trace.received(REPLIES[0])
    trace.report("objective_met", Resolution(report="THE REPORT"))
    trace.status("waiting", 1, 5, SENT)
    assert record.wave == 1  # callers still get their record
    assert [f.name for f in trace.folder.iterdir()] == ["status.json"]
    text = (trace.folder / "status.json").read_text(encoding="utf-8")
    assert "slowest" not in text
    status = trace.read_status()
    assert [(p.channel, p.send_at, p.text) for p in status.pending] == [("email", SENT[0].send_at, "")]
    assert trace.records() == [] and trace.messages() == [] and trace.read_report() is None


def test_register_off_fail_keeps_only_the_first_sentence(tmp_path):
    trace = Trace(tmp_path / "run", register=False)
    trace.fail("planner: no valid Paths after 4 model calls (limit 4). Last message: Alex said the sync is nightly")
    assert trace.read_status().error == "planner: no valid Paths after 4 model calls (limit 4)."


def test_register_on_fail_keeps_the_whole_error(trace):
    trace.fail("planner: no valid Paths. Last message: text")
    assert trace.read_status().error.endswith("Last message: text")
