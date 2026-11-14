from datetime import timedelta

import pytest
from conftest import NOW, interaction, load

from pequod.channels import build_channels
from pequod.channels.base import Channel, MockChannel
from pequod.channels.email import EmailMock
from pequod.channels.mock_hub import MockHub
from pequod.channels.sms import SmsMock
from pequod.channels.whatsapp import WhatsAppMock
from pequod.types import Interaction


@pytest.fixture
def hub(tmp_path):
    return MockHub(tmp_path / "hub.db")


def clock():
    return NOW


def test_mocks_are_channels_with_their_name():
    assert [c.name for c in (EmailMock, SmsMock, WhatsAppMock)] == ["email", "sms", "whatsapp"]
    assert all(issubclass(c, MockChannel) and issubclass(c, Channel) for c in (EmailMock, SmsMock, WhatsAppMock))


def test_send_writes_to_the_hub(hub, rules):
    sent_id = EmailMock(rules["email"], hub, clock).send(Interaction(**interaction("email")))
    assert sent_id == "email-1"
    assert [(m["body"], m["at"]) for m in hub.sent("email")] == [("Hi Alex, which report is slowest?", NOW)]


def test_send_rejects_another_channels_interaction(hub, rules):
    with pytest.raises(ValueError, match="email.*sms"):
        SmsMock(rules["sms"], hub, clock).send(Interaction(**interaction("email")))
    assert hub.sent() == []


def test_fetch_replies_reads_only_its_channel(hub, rules):
    hub.add_reply("sms", "sms reply", NOW)
    hub.add_reply("email", "email reply", NOW + timedelta(minutes=1))
    assert [r.body for r in SmsMock(rules["sms"], hub, clock).fetch_replies(NOW)] == ["sms reply"]


def test_build_channels_uses_the_engagement_channels(cfg, hub, rules):
    channels = build_channels(cfg.channels, ["email", "sms"], hub, clock)
    assert {name: type(c) for name, c in channels.items()} == {"email": EmailMock, "sms": SmsMock}
    assert channels["sms"].rules == rules["sms"]


def test_build_channels_unknown_channel_raises(cfg, hub):
    with pytest.raises(ValueError, match="fax"):
        build_channels(cfg.channels, ["email", "fax"], hub, clock)


def test_live_mode_stops_with_a_stage_6_message(hub):
    with pytest.raises(NotImplementedError, match="Stage 6"):
        build_channels(load(["channels=live"]).channels, ["email"], hub, clock)
