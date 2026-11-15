import pytest
from pydantic import ValidationError

from pequod.types import Engagement, Interaction, Path, StopSignal, Wave

AWARE = "2026-11-16T10:00:00+01:00"


def test_engagement_validates_default_config(engagement):
    assert engagement.persona.name == "Alex Carter"
    assert engagement.persona.features["timezone"] == "Europe/Berlin"
    assert engagement.channels["sms"].features["hours"] == "12-18"


def test_engagement_needs_a_channel():
    with pytest.raises(ValidationError):
        Engagement(objective="o", persona={"name": "A"}, channels={})


def test_wave_rejects_naive_send_at():
    wave = dict(intent="open_door", strategy="plain_message", channel="email")
    with pytest.raises(ValidationError):
        Wave(**wave, send_at="2026-11-16T10:00:00")
    assert Wave(**wave, send_at=AWARE).send_at.utcoffset() is not None


def test_interaction_optional_fields_default_none():
    interaction = Interaction(channel="sms", send_at=AWARE, body="Hi")
    assert interaction.subject is None and interaction.payload is None


def test_path_starts_without_waves():
    assert Path(subgoals=["a"], rationale="r").waves == []


@pytest.mark.parametrize(
    "flags, expected",
    [
        ({}, False),
        ({"objective_met": True}, True),
        ({"solution_accepted": True}, True),
        ({"opt_out": True}, True),
    ],
)
def test_stop_signal_stop(flags, expected):
    assert StopSignal(**flags).stop is expected
