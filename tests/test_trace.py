import json

import pytest
from conftest import NOW, interaction, path, wave

from pequod.trace import Trace
from pequod.types import Interaction, Path, Reply, Resolution, StopSignal, WaveRecord

PATHS = [Path(**path(wave("email", "open_door")))]
SENT = [Interaction(**interaction("email"))]
REPLIES = [Reply(id="whatsapp-2", channel="whatsapp", body="Our stock numbers are a day old", received_at=NOW)]
SIGNAL = StopSignal(root_problem_stated=True, evidence="a day old")


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
    second = trace.record(2, PATHS, [], [], SIGNAL, "root_problem_stated")
    assert len(lines(trace)) == 2 and trace.records() == [first, second]
    assert [(r.wave, r.snapshot, r.reason) for r in trace.records()] == [
        (1, "graph_0.json", None),
        (2, "graph_1.json", "root_problem_stated"),
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
  Stop signal: root_problem_stated · "a day old"
  Decision: stop (root_problem_stated)"""


def test_card_shows_paths_sent_replies_signal_and_decision(trace):
    trace.record(1, PATHS, SENT, REPLIES, SIGNAL, "root_problem_stated")
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
    trace.record(1, PATHS, [], [], StopSignal(opt_out=True, root_problem_stated=True, evidence="stop"), "opt_out")
    assert 'Stop signal: root_problem_stated, opt_out · "stop"' in trace.explain()
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
