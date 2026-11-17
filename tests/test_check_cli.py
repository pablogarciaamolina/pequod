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
        return [Reply(id="r1", channel="pepe", body="Got it, thanks 👍", received_at=datetime.now(timezone.utc))]


@pytest.fixture
def live(monkeypatch):
    """`build_channels` replaced: records what it was asked for and hands out one fake live channel.
    Its 2nd argument is now the persona channels (name -> {platform, address})."""
    channel, seen = FakeLive(), {}

    def build(config, persona, hub, clock):
        seen.update(config=dict(config), persona=dict(persona), hub=hub)
        return {name: channel for name in config}

    monkeypatch.setattr(cli, "build_channels", build)
    monkeypatch.setattr(cli, "load_dotenv", lambda: None)  # never load real credentials in tests
    channel.seen = seen
    return channel


def test_check_sends_one_test_message(live, capsys):
    assert cli.check(["pepe"]) == 0
    (sent,) = live.sent
    assert sent.channel == "pepe" and "test" in sent.body.lower() and "Pequod" in sent.body and sent.subject
    assert len(sent.body) <= 160  # also fits an SMS
    assert set(live.seen["config"]) == {"pepe"} and live.seen["hub"] is None  # only the named system channel is built
    assert all(c.mode == "live" for c in live.seen["config"].values())  # always live, whatever the default is
    out = capsys.readouterr().out
    assert "<id-1@test>" in out and "julius.muth@revel8.ai" in out  # pepe reaches the persona's work_email


def test_check_replies_lists_the_last_24_hours(live, capsys):
    assert cli.check(["pepe", "replies"]) == 0
    assert live.sent == []
    age = datetime.now(timezone.utc) - live.asked[0]
    assert timedelta(hours=23, minutes=59) < age < timedelta(hours=24, minutes=1)
    assert "Got it, thanks 👍" in capsys.readouterr().out


def test_check_passes_overrides(live):
    assert cli.check(["stephan", "engagement.channels.company_sms.address=+99 999 999"]) == 0
    assert live.seen["persona"]["company_sms"]["address"] == "+99 999 999"  # the override reaches the persona map
    assert cli.check(["pepe", "replies", "engagement.channels.work_email.address=test@change-me.example"]) == 0
    assert live.seen["persona"]["work_email"]["address"] == "test@change-me.example"


@pytest.mark.parametrize("args", [[], ["fax"], ["pepe", "~channels.pepe"]])
def test_check_usage_and_unknown_channel(live, args, capsys):
    assert cli.check(args) == 2
    assert live.sent == [] and len(capsys.readouterr().err.strip().splitlines()) == 1


def test_check_with_missing_credentials_or_placeholder_sends_nothing(monkeypatch, capsys):
    """With the real `build_channels`: a placeholder recipient must never be mailed."""
    for variable in ("EMAIL_ADDRESS", "EMAIL_APP_PASSWORD"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setattr(cli, "load_dotenv", lambda: None)
    def no_network(*args, **kwargs):
        raise AssertionError("a test tried to open a mail connection")

    monkeypatch.setattr("smtplib.SMTP_SSL", no_network)
    assert cli.check(["pepe", "engagement.channels.work_email.address=x@example.com"]) == 2
    assert "EMAIL_ADDRESS" in capsys.readouterr().err
    monkeypatch.setenv("EMAIL_ADDRESS", "us@gmail.test")
    monkeypatch.setenv("EMAIL_APP_PASSWORD", "secret-app-password")
    assert cli.check(["pepe", "engagement.channels.work_email.address=x@example.com"]) == 2
    err = capsys.readouterr().err
    assert "placeholder" in err and "secret-app-password" not in err


def test_check_reports_a_platform_error(monkeypatch, capsys):
    channel = FakeLive(fail=ChannelError("pepe: could not send to x: SMTPAuthenticationError"))
    monkeypatch.setattr(cli, "build_channels", lambda config, persona, hub, clock: {"pepe": channel})
    monkeypatch.setattr(cli, "load_dotenv", lambda: None)
    assert cli.check(["pepe"]) == 1
    assert "could not send" in capsys.readouterr().err


def test_main_dispatches_check(live, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["pequod", "check", "pepe"])
    with pytest.raises(SystemExit) as e:
        cli.main()
    assert e.value.code == 0 and len(live.sent) == 1


@pytest.mark.parametrize("args", [["pepe", "channels=mock"], ["pepe", "channels.pepe.mode=mock"],
                                  ["pepe", "engagement=live_test", "replies"], ["pepe", "engagement=nope"]])
def test_check_refuses_mock_mode_and_bad_overrides(live, args, capsys):
    assert cli.check(args) == 2
    assert live.sent == [] and live.asked == []
    assert len(capsys.readouterr().err.strip().splitlines()) == 1
