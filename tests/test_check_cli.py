import sys
from datetime import datetime, timedelta, timezone

import pytest

from pequod import main as cli
from pequod.channels.base import ChannelError
from pequod.types import Reply


class FakeLive:
    def __init__(self, fail=None):
        self.sent, self.asked, self.fail = [], [], fail

    def send(self, interaction):
        if self.fail:
            raise self.fail
        self.sent.append(interaction)
        return "<id-1@test>"

    def fetch_replies(self, since):
        self.asked.append(since)
        return [Reply(id="r1", channel="email", body="Got it, thanks 👍", received_at=datetime.now(timezone.utc))]


@pytest.fixture
def live(monkeypatch):
    """`build_channels` replaced: records what it was asked for and hands out one fake live channel."""
    channel, seen = FakeLive(), {}

    def build(config, addresses, hub, clock):
        seen.update(config=config, addresses=dict(addresses), hub=hub)
        return {name: channel for name in addresses}

    monkeypatch.setattr(cli, "build_channels", build)
    monkeypatch.setattr(cli, "load_dotenv", lambda: None)  # never load real credentials in tests
    channel.seen = seen
    return channel


def test_check_sends_one_test_message(live, capsys):
    assert cli.check(["email"]) == 0
    (sent,) = live.sent
    assert sent.channel == "email" and "test" in sent.body.lower() and "Pequod" in sent.body and sent.subject
    assert len(sent.body) <= 160  # also fits an SMS
    assert live.seen["addresses"] == {"email": "alex@northwind.example"} and live.seen["hub"] is None
    assert all(c.mode == "live" for c in live.seen["config"].values())  # always live, whatever the default is
    out = capsys.readouterr().out
    assert "<id-1@test>" in out and "alex@northwind.example" in out


def test_check_replies_lists_the_last_24_hours(live, capsys):
    assert cli.check(["email", "replies"]) == 0
    assert live.sent == []
    age = datetime.now(timezone.utc) - live.asked[0]
    assert timedelta(hours=23, minutes=59) < age < timedelta(hours=24, minutes=1)
    assert "Got it, thanks 👍" in capsys.readouterr().out


def test_check_passes_overrides(live):
    assert cli.check(["sms", "engagement=live_test"]) == 0
    assert live.seen["addresses"] == {"sms": "+00 000 000"}
    assert cli.check(["email", "replies", "engagement=live_test"]) == 0
    assert live.seen["addresses"] == {"email": "your-test-mailbox@change-me.example"}


@pytest.mark.parametrize("args", [[], ["fax"], ["email", "~engagement.channels.email"]])
def test_check_usage_and_unknown_channel(live, args, capsys):
    assert cli.check(args) == 2
    assert live.sent == [] and len(capsys.readouterr().err.strip().splitlines()) == 1


def test_check_with_missing_credentials_or_placeholder_sends_nothing(monkeypatch, capsys):
    """With the real `build_channels`: the demo persona's address must never be mailed."""
    for variable in ("EMAIL_ADDRESS", "EMAIL_APP_PASSWORD"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setattr(cli, "load_dotenv", lambda: None)
    def no_network(*args, **kwargs):
        raise AssertionError("a test tried to open a mail connection")

    monkeypatch.setattr("smtplib.SMTP_SSL", no_network)
    assert cli.check(["email"]) == 2
    assert "EMAIL_ADDRESS" in capsys.readouterr().err
    monkeypatch.setenv("EMAIL_ADDRESS", "us@gmail.test")
    monkeypatch.setenv("EMAIL_APP_PASSWORD", "secret-app-password")
    assert cli.check(["email"]) == 2
    err = capsys.readouterr().err
    assert "placeholder" in err and "secret-app-password" not in err


def test_check_reports_a_platform_error(monkeypatch, capsys):
    channel = FakeLive(fail=ChannelError("email: could not send to x: SMTPAuthenticationError"))
    monkeypatch.setattr(cli, "build_channels", lambda config, addresses, hub, clock: {"email": channel})
    monkeypatch.setattr(cli, "load_dotenv", lambda: None)
    assert cli.check(["email"]) == 1
    assert "could not send" in capsys.readouterr().err


def test_main_dispatches_check(live, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["pequod", "check", "email"])
    with pytest.raises(SystemExit) as e:
        cli.main()
    assert e.value.code == 0 and len(live.sent) == 1


@pytest.mark.parametrize("args", [["email", "channels=mock"], ["email", "channels.email.mode=mock"],
                                  ["email", "engagement=live_test", "replies"], ["email", "engagement=nope"]])
def test_check_refuses_mock_mode_and_bad_overrides(live, args, capsys):
    assert cli.check(args) == 2
    assert live.sent == [] and live.asked == []
    assert len(capsys.readouterr().err.strip().splitlines()) == 1
