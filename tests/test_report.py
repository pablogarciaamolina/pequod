import json
import sys

import pytest

from pequod import main as cli
from pequod.visualizations.report import build_html, write_report


def make_run(folder):
    """A minimal run folder: one graph snapshot, a report, a trace line and an agent run."""
    folder.mkdir(parents=True, exist_ok=True)
    graph = {
        "directed": True, "multigraph": True, "graph": {},
        "nodes": [
            {"id": "julius_muth", "kind": "persona", "name": "Julius Muth", "org": "Revel8"},
            {"id": "work_email", "kind": "channel", "name": "work_email", "platform": "email"},
            {"id": "a_fact", "kind": "fact", "name": "likes dogs"},
        ],
        "edges": [
            {"source": "julius_muth", "target": "work_email", "relation": "reachable_via", "attrs": {}, "key": 0},
            {"source": "a_fact", "target": "julius_muth", "relation": "about", "attrs": {}, "key": 0},
        ],
    }
    (folder / "graph_0.json").write_text(json.dumps(graph), encoding="utf-8")
    (folder / "report.md").write_text("Stop reason: objective_met\nOUTCOME: learned the dog's name.", encoding="utf-8")
    (folder / "trace.jsonl").write_text(json.dumps({
        "wave": 1, "snapshot": "graph_0.json", "paths": ["Start -> open_door on pepe"],
        "interactions": [{"channel": "pepe", "send_at": "2026-11-16T10:00:00+00:00", "text": "Hi", "cut": False}],
        "replies": [{"id": "pepe-1", "channel": "pepe", "body": "hello", "received_at": "2026-11-16T10:05:00+00:00"}],
        "stop_signal": {"objective_met": True, "solution_accepted": False, "opt_out": False, "evidence": "it's Rex"},
        "reason": "objective_met",
    }) + "\n", encoding="utf-8")
    (folder / "agents.jsonl").write_text(json.dumps({
        "agent": "strategist",
        "messages": [
            {"type": "system", "content": "You are the Strategist."},
            {"type": "ai", "content": "", "reasoning": "I will ask about his dog.", "tool_calls": [{"name": "graph_summary", "args": {}}]},
            {"type": "tool", "name": "graph_summary", "content": "[julius_muth] persona"},
        ],
        "error": "",
    }) + "\n", encoding="utf-8")


def test_build_html_has_graph_waves_agents_and_report(tmp_path):
    make_run(tmp_path / "run")
    html = build_html(tmp_path / "run")
    assert html.startswith("<!doctype html>")
    assert "<svg" in html and html.count('class="node"') == 3          # three graph nodes drawn
    assert "likes dogs" in html and "reachable_via" in html            # a node and an edge label
    assert "learned the dog&#x27;s name." in html                      # report, HTML-escaped
    assert "Wave 1" in html and "objective_met" in html                # the wave card
    assert 'details class="agent"' in html and "I will ask about his dog." in html  # agent reasoning


def test_write_report_creates_the_file(tmp_path):
    make_run(tmp_path / "run")
    out = write_report(tmp_path / "run")
    assert out == (tmp_path / "run" / "report.html") and out.is_file()


def test_report_handles_a_run_without_register(tmp_path):
    (tmp_path / "bare").mkdir()
    html = build_html(tmp_path / "bare")  # no snapshots, no trace, no agents
    assert "No graph snapshot" in html and "No report." in html and "No agent runs recorded" in html


def test_report_command_rejects_a_missing_folder(capsys):
    assert cli.report(["does-not-exist"]) == 2
    assert "Usage: pequod report" in capsys.readouterr().err


def test_main_dispatches_report(tmp_path, monkeypatch):
    make_run(tmp_path / "run")
    monkeypatch.setattr(sys, "argv", ["pequod", "report", str(tmp_path / "run")])
    with pytest.raises(SystemExit) as e:
        cli.main()
    assert e.value.code == 0 and (tmp_path / "run" / "report.html").is_file()
