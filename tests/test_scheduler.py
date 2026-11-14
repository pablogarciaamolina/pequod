import io
import os
import time
from datetime import datetime, timedelta, timezone

import pytest
from conftest import NOW, Clock, FakeOperator

from pequod.channels import build_channels
from pequod.channels.mock_hub import MockHub
from pequod.engagement import Operator, Scheduler
from pequod.types import Interaction

# NOW is 08:00 UTC


def at(hour, channel="email", body="hi"):
    return Interaction(channel=channel, send_at=NOW.replace(hour=hour), body=body)


@pytest.fixture
def hub(tmp_path):
    return MockHub(tmp_path / "hub.db")


def scheduler(cfg, hub, clock, script=(), window=24):
    operator = FakeOperator(clock, script)
    channels = build_channels(cfg.channels, ["email", "sms", "whatsapp"], hub, clock)
    return Scheduler(channels, operator, window, clock), operator


def test_sends_at_send_at_then_waits_the_window(cfg, hub):
    clock = Clock()
    s, operator = scheduler(cfg, hub, clock)
    sent, stop = s.run([at(10)])
    assert [m["at"] for m in hub.sent()] == [NOW.replace(hour=10)]
    assert sent == [at(10)] and stop is False
    assert clock.now == NOW.replace(hour=10) + timedelta(hours=24)
    assert operator.waits == [2 * 3600, 24 * 3600]


def test_past_send_at_is_sent_immediately(cfg, hub):
    clock = Clock()
    s, _ = scheduler(cfg, hub, clock)
    sent, _ = s.run([at(6)])
    assert [m["at"] for m in hub.sent()] == [NOW] and len(sent) == 1


def test_enter_drops_unsent(cfg, hub):
    s, _ = scheduler(cfg, hub, Clock(), ["ok"])
    assert s.run([at(10)]) == ([], False)
    assert hub.sent() == []


def test_enter_after_a_send_keeps_what_was_sent(cfg, hub):
    s, _ = scheduler(cfg, hub, Clock(), ["ok"])
    sent, stop = s.run([at(6), at(12, "sms")])
    assert [i.channel for i in sent] == ["email"] and stop is False
    assert [m["channel"] for m in hub.sent()] == ["email"]


def test_s_sends_everything_now(cfg, hub):
    clock = Clock()
    s, _ = scheduler(cfg, hub, clock, ["send", "ok"])
    sent, stop = s.run([at(12, "sms"), at(10)])
    assert [i.channel for i in sent] == ["email", "sms"] and stop is False
    assert [m["at"] for m in hub.sent()] == [NOW, NOW]


def test_q_stops(cfg, hub):
    s, _ = scheduler(cfg, hub, Clock(), ["stop"])
    assert s.run([at(10)]) == ([], True)


def test_two_interactions_are_sent_in_time_order_and_the_window_counts_from_the_last(cfg, hub):
    clock = Clock()
    s, _ = scheduler(cfg, hub, clock, window=1)
    sent, _ = s.run([at(12, "sms"), at(10)])
    assert [(m["channel"], m["at"].hour) for m in hub.sent()] == [("email", 10), ("sms", 12)]
    assert [i.channel for i in sent] == ["email", "sms"]
    assert clock.now == NOW.replace(hour=13)


def test_nothing_pending_returns_at_once(cfg, hub):
    s, operator = scheduler(cfg, hub, Clock())
    assert s.run([]) == ([], False)
    assert operator.waits == []


def test_send_at_in_another_timezone(cfg, hub):
    clock = Clock()
    s, _ = scheduler(cfg, hub, clock)
    berlin = datetime(2026, 11, 16, 10, 0, tzinfo=timezone(timedelta(hours=1)))  # 09:00 UTC
    s.run([Interaction(channel="email", send_at=berlin, body="hi")])
    assert hub.sent()[0]["at"] == NOW.replace(hour=9)


def test_operator_maps_lines():
    operator = Operator(io.StringIO("\nq\nxyz\nS\n"))
    assert [operator.wait(2) for _ in range(3)] == ["ok", "stop", "send"]


def test_operator_timeout_returns_none():
    read, write = os.pipe()  # a stream that stays open and silent, like an idle keyboard
    stream, writer = os.fdopen(read), os.fdopen(write, "w")
    try:
        assert Operator(stream).wait(0.01) is None
    finally:
        writer.close()  # end of input: the reader thread finishes; the read end is left to the OS


def test_operator_closed_stream_returns_none():
    assert Operator(io.StringIO("")).wait(0.01) is None


def test_sent_carries_the_real_send_time(cfg, hub):
    """The Updater must record when a message really went out, not when it was planned."""
    s, _ = scheduler(cfg, hub, Clock(), ["send", "ok"])
    sent, _ = s.run([at(10), at(6, "sms")])
    assert [i.send_at for i in sent] == [NOW, NOW]


def test_run_discards_keys_typed_before_the_wait(cfg, hub):
    s, operator = scheduler(cfg, hub, Clock(), ["ok"])
    s.run([at(10)])
    assert operator.cleared == 1


def typed(text):
    operator = Operator(io.StringIO(text))
    for _ in range(1000):  # let the reader thread pick the lines up
        if operator.lines.qsize() == text.count("\n"):
            break
        time.sleep(0.001)
    return operator


def test_operator_clear_drops_lines_typed_earlier():
    operator = typed("\n\n")
    operator.clear()
    assert operator.wait(0.01) is None
