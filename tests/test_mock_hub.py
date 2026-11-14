from datetime import timedelta, timezone

import pytest
from conftest import NOW, interaction

from pequod.channels.mock_hub import MockHub
from pequod.types import Interaction, Reply


@pytest.fixture
def hub(tmp_path):
    return MockHub(tmp_path / "hub.db")


def test_reply_round_trip(hub):
    assert hub.add_reply("sms", "ok", NOW) == "sms-1"
    assert hub.replies("sms", NOW) == [Reply(id="sms-1", channel="sms", body="ok", received_at=NOW)]


def test_replies_are_per_channel_and_since(hub):
    hub.add_reply("sms", "old", NOW - timedelta(hours=1))
    hub.add_reply("email", "other channel", NOW)
    hub.add_reply("sms", "first", NOW)
    hub.add_reply("sms", "second", NOW + timedelta(minutes=5))
    assert [r.body for r in hub.replies("sms", NOW)] == ["first", "second"]


def test_times_in_another_timezone_compare_correctly(hub):
    berlin = NOW.astimezone(timezone(timedelta(hours=1)))
    hub.add_reply("sms", "ok", berlin)
    assert hub.replies("sms", NOW)[0].received_at == NOW
    assert hub.replies("sms", NOW + timedelta(seconds=1)) == []


def test_sent_keeps_subject_and_payload(hub):
    sent = Interaction(**interaction("email"), subject="Reports", payload={"url": "https://kb.example/erp-sync"})
    assert hub.add_sent(sent, NOW) == "email-1"
    assert hub.sent("email") == [
        {"channel": "email", "at": NOW, "body": sent.body, "subject": "Reports", "payload": sent.payload}
    ]


def test_sent_and_replies_do_not_mix(hub):
    hub.add_sent(Interaction(**interaction("sms")), NOW)
    hub.add_reply("sms", "ok", NOW)
    assert len(hub.sent()) == 1 and len(hub.replies("sms", NOW)) == 1
    assert hub.sent("email") == []


def test_two_hubs_on_one_file_share_data(tmp_path):
    MockHub(tmp_path / "hub.db").add_reply("sms", "ok", NOW)
    assert len(MockHub(tmp_path / "hub.db").replies("sms", NOW)) == 1


def test_creates_the_folder(tmp_path):
    MockHub(tmp_path / "a" / "b" / "hub.db").add_reply("sms", "ok", NOW)


def test_time_without_a_timezone_is_rejected(hub):
    with pytest.raises(ValueError, match="timezone"):
        hub.add_reply("sms", "ok", NOW.replace(tzinfo=None))
