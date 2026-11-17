from datetime import timedelta

import pytest
from conftest import NOW, interaction, load, personas
from omegaconf import OmegaConf

from pequod.channels import build_channels
from pequod.channels.base import Channel, MockChannel
from pequod.channels.email import EmailMock
from pequod.channels.mock_hub import MockHub
from pequod.channels.sms import SmsMock
from pequod.channels.whatsapp import WhatsAppMock
from pequod.types import ChannelRules, Interaction

RULES = {"max_length": 2000, "subject": True, "links_ok": True}
R = ChannelRules.model_validate(RULES)


@pytest.fixture
def hub(tmp_path):
    return MockHub(tmp_path / "hub.db")


def clock():
    return NOW


def chan_config(**instances):
    """A channels config keyed by instance name; each value has kind, mode, rules (+ credentials)."""
    for spec in instances.values():
        spec.setdefault("mode", "mock")
        spec.setdefault("rules", RULES)
        spec.setdefault("credentials", {})
    return OmegaConf.create(instances)


def test_concrete_classes_declare_their_kind():
    assert [c.platform for c in (EmailMock, SmsMock, WhatsAppMock)] == ["email", "sms", "whatsapp"]
    assert all(issubclass(c, MockChannel) and issubclass(c, Channel) for c in (EmailMock, SmsMock, WhatsAppMock))


def test_instance_name_is_separate_from_kind(hub, rules):
    channel = EmailMock("email_work", R, hub, clock)
    assert channel.name == "email_work" and channel.platform == "email"


def test_send_writes_to_the_hub(hub, rules):
    sent_id = EmailMock("email", R, hub, clock).send(Interaction(**interaction("email")))
    assert sent_id == "email-1"
    assert [(m["body"], m["at"]) for m in hub.sent("email")] == [("Hi Alex, which report is slowest?", NOW)]


def test_two_instances_of_the_same_kind_stay_separate(hub, rules):
    EmailMock("email_work", R, hub, clock).send(Interaction(**interaction("email_work", "to work")))
    EmailMock("email_boss", R, hub, clock).send(Interaction(**interaction("email_boss", "to boss")))
    assert [m["body"] for m in hub.sent("email_work")] == ["to work"]
    assert [m["body"] for m in hub.sent("email_boss")] == ["to boss"]


def test_accept_checks_the_instance_name(hub, rules):
    with pytest.raises(ValueError, match="email_work"):
        EmailMock("email_work", R, hub, clock).send(Interaction(**interaction("email_boss")))
    assert hub.sent() == []


def test_send_rejects_another_channels_interaction(hub, rules):
    with pytest.raises(ValueError, match="email.*sms"):
        SmsMock("sms", R, hub, clock).send(Interaction(**interaction("email")))
    assert hub.sent() == []


def test_fetch_replies_reads_only_its_channel(hub, rules):
    hub.add_reply("sms", "sms reply", NOW)
    hub.add_reply("email", "email reply", NOW + timedelta(minutes=1))
    assert [r.body for r in SmsMock("sms", R, hub, clock).fetch_replies(NOW)] == ["sms reply"]


def test_build_channels_builds_one_object_per_system_channel(cfg, hub, rules):
    channels = build_channels(cfg.channels, personas(cfg), hub, clock)
    assert {name: type(c) for name, c in channels.items()} == {"pepe": EmailMock, "stephan": SmsMock, "melina": WhatsAppMock}
    assert channels["stephan"].rules == rules["stephan"]


PERSONA = {"work": {"platform": "email", "address": "a@x.test"},
           "home": {"platform": "email", "address": "b@x.test"},
           "phone": {"platform": "sms", "address": "+1"}}


def test_build_channels_selects_the_class_by_platform(hub):
    config = chan_config(pepe={"platform": "email", "target": "work"},
                         boss={"platform": "email", "target": "home"},
                         cto={"platform": "sms", "target": "phone"})
    channels = build_channels(config, PERSONA, hub, clock)
    assert {name: type(c) for name, c in channels.items()} == {"pepe": EmailMock, "boss": EmailMock, "cto": SmsMock}
    assert channels["pepe"].name == "pepe" and channels["pepe"].platform == "email"


def test_two_system_channels_can_target_the_same_persona_channel(hub):
    config = chan_config(pepe={"platform": "email", "target": "work"}, boss={"platform": "email", "target": "work"})
    channels = build_channels(config, PERSONA, hub, clock)
    assert set(channels) == {"pepe", "boss"}  # two threads into one inbox


def test_build_channels_unknown_platform_fails_clearly(hub):
    config = chan_config(odd={"platform": "fax", "target": "work"})
    with pytest.raises(ValueError, match="fax"):
        build_channels(config, PERSONA, hub, clock)


def test_build_channels_missing_target_fails_clearly(hub):
    config = chan_config(pepe={"platform": "email", "target": "ghost"})
    with pytest.raises(ValueError, match="ghost"):
        build_channels(config, PERSONA, hub, clock)


def test_build_channels_platform_mismatch_fails_clearly(hub):
    config = chan_config(pepe={"platform": "email", "target": "phone"})  # phone is sms
    with pytest.raises(ValueError, match="same platform"):
        build_channels(config, PERSONA, hub, clock)


def test_live_mode_missing_credentials_stops_before_building(hub):
    cfg = load(["channels=live"])
    with pytest.raises(ValueError, match="EMAIL_ADDRESS"):
        build_channels(cfg.channels, personas(cfg), hub, clock, {})
