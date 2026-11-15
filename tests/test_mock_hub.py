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


# --- simulator support: run start, operator commands, conversation (Stage 5) ---

import sqlite3

from pequod.types import Message


def test_run_folder_is_none_before_any_run(hub):
    assert hub.run_folder() is None


def test_start_run_clears_messages_and_commands_and_stores_the_folder(hub, tmp_path):
    hub.add_sent(Interaction(**interaction("sms")), NOW)
    hub.add_reply("sms", "old reply", NOW)
    hub.add_command("send")
    hub.start_run(tmp_path / "runs" / "one")
    assert hub.sent() == [] and hub.replies("sms", NOW) == [] and hub.take_commands() == []
    assert hub.run_folder() == tmp_path / "runs" / "one"
    hub.start_run(tmp_path / "runs" / "two")
    assert hub.run_folder() == tmp_path / "runs" / "two"


def test_commands_are_taken_once_in_order(hub):
    hub.add_command("send")
    hub.add_command("ok")
    assert hub.take_commands() == ["send", "ok"]
    assert hub.take_commands() == []


def test_unknown_command_is_rejected(hub):
    with pytest.raises(ValueError, match="send, ok, stop"):
        hub.add_command("explode")
    assert hub.take_commands() == []


def test_conversation_has_both_directions_in_order(hub):
    first = Interaction(**interaction("email"), subject="Reports", payload={"url": "https://kb.example/erp-sync"})
    hub.add_sent(first, NOW)
    hub.add_reply("email", "Which reports?", NOW + timedelta(minutes=5))
    hub.add_sent(Interaction(**interaction("email", "The weekly ones.")), NOW + timedelta(minutes=9))
    hub.add_reply("sms", "other channel", NOW)
    talk = hub.conversation("email")
    assert all(type(m) is Message for m in talk)
    assert [(m.direction, m.body) for m in talk] == [
        ("out", first.body), ("in", "Which reports?"), ("out", "The weekly ones."),
    ]
    assert (talk[0].subject, talk[0].payload, talk[0].at) == ("Reports", first.payload, NOW)
    assert (talk[1].subject, talk[1].payload) == (None, None)


def test_existing_hub_file_from_an_older_version_still_opens(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, direction TEXT, channel TEXT, at TEXT, "
                   "body TEXT, subject TEXT, payload TEXT)")
    db.close()
    hub = MockHub(path)
    hub.add_command("ok")
    hub.start_run(tmp_path)
    assert hub.run_folder() == tmp_path


def test_two_callers_never_take_the_same_command(hub):
    """The engine's poller and clear() can ask at the same moment."""
    import threading

    for _ in range(30):
        for command in ("send", "ok", "stop", "send", "ok"):
            hub.add_command(command)
        barrier, taken = threading.Barrier(2), []

        def take():
            barrier.wait()
            taken.extend(hub.take_commands())

        threads = [threading.Thread(target=take) for _ in range(2)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        assert sorted(taken) == ["ok", "ok", "send", "send", "stop"]
