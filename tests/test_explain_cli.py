import subprocess
import sys

import pytest
from conftest import NOW, interaction, path, wave

from pequod import main as cli
from pequod.trace import Trace
from pequod.types import Interaction, Path, Reply, Resolution, StopSignal

PATHS = [Path(**path(wave("email", "open_door")))]


@pytest.fixture
def run(tmp_path):
    trace = Trace(tmp_path / "run")
    reply = Reply(id="sms-1", channel="sms", body="Grüße 👍", received_at=NOW)
    trace.record(1, PATHS, [Interaction(**interaction("email"))], [reply], StopSignal(), "max_iterations")
    trace.report("max_iterations", Resolution(report="THE REPORT"))
    return trace.folder


def test_explain_cli_prints_the_cards(run, capsys):
    assert cli.explain([str(run)]) == 0
    out = capsys.readouterr().out
    assert "Wave 1" in out and "THE REPORT" in out


@pytest.mark.parametrize("case", ["no argument", "two arguments", "missing folder", "folder without trace"])
def test_explain_cli_errors(case, tmp_path, capsys):
    args = {
        "no argument": [],
        "two arguments": ["a", "b"],
        "missing folder": [str(tmp_path / "nope")],
        "folder without trace": [str(tmp_path)],
    }[case]
    assert cli.explain(args) == 2
    captured = capsys.readouterr()
    assert captured.out == "" and len(captured.err.strip().splitlines()) == 1
    assert not (tmp_path / "nope").exists()  # explaining must not create anything


def test_main_dispatches_explain(run, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["pequod", "explain", str(run)])
    with pytest.raises(SystemExit) as e:
        cli.main()
    assert e.value.code == 0 and "Wave 1" in capsys.readouterr().out


def test_explain_prints_non_ascii_through_a_pipe(run):
    """A pipe on Windows is not UTF-8 by default; the command must not crash on an emoji."""
    out = subprocess.run(["pequod", "explain", str(run)], capture_output=True, timeout=60)
    assert out.returncode == 0
    assert "Grüße 👍" in out.stdout.decode("utf-8")
