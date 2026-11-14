import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone

import pytest

from pequod import main as cli
from pequod.channels.mock_hub import MockHub

START = datetime.now(timezone.utc) - timedelta(minutes=1)


@pytest.fixture(autouse=True)
def workdir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # the hub path in the config is relative to the start folder


def replies(channel):
    return [r.body for r in MockHub("runs/mock_hub.db").replies(channel, START)]


def test_reply_writes_into_the_hub(capsys):
    assert cli.reply(["whatsapp", "stock numbers are a day old"]) == 0
    assert replies("whatsapp") == ["stock numbers are a day old"]
    out = capsys.readouterr().out
    assert "whatsapp" in out and str(Path("runs/mock_hub.db").resolve()) in out  # shows which file was written


def test_reply_unknown_channel(capsys):
    assert cli.reply(["fax", "x"]) == 2
    assert "email, sms, whatsapp" in capsys.readouterr().err
    assert all(replies(c) == [] for c in ("email", "sms", "whatsapp"))


@pytest.mark.parametrize("args", [[], ["sms"], ["sms", "a", "b"], ["sms", "  "]])
def test_reply_usage(args, capsys):
    assert cli.reply(args) == 2
    assert 'pequod reply <channel> "text"' in capsys.readouterr().err


def test_main_dispatches_reply(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["pequod", "reply", "sms", "hi"])
    with pytest.raises(SystemExit) as e:
        cli.main()
    assert e.value.code == 0 and replies("sms") == ["hi"]
