from conftest import ANGLE, NOW, READ, call, fake, interaction

from pequod.agents.reviewer import Reviewer
from pequod.types import Interaction, Review

DRAFTS = [Interaction(**interaction("email")), Interaction(**interaction("sms", "Quick one, Alex"))]


def review(*channels, notes="Shortened the SMS."):
    return call("Review", interactions=[interaction(c) for c in channels], notes=notes)


def run(graph, rules, *messages):
    model = fake(*messages)
    return model, Reviewer(model, graph, rules, max_steps=4, angle=ANGLE).run(DRAFTS, NOW)


def test_returns_review_with_same_channels(graph, rules):
    _, out = run(graph, rules, review("email", "sms"))
    assert type(out) is Review
    assert [i.channel for i in out.interactions] == ["email", "sms"] and out.notes


def test_tools(graph, rules):
    model, _ = run(graph, rules, review("email", "sms"))
    assert set(model.bound) == READ | {"channel_rules", "Review"}


def test_changed_channel_is_rejected_then_fixed(graph, rules):
    model, out = run(graph, rules, review("email", "whatsapp"), review("email", "sms"))
    assert [i.channel for i in out.interactions] == ["email", "sms"]
    assert "Keep the same interactions and channels" in model.seen[1][-1].content


def test_dropped_interaction_is_rejected_then_fixed(graph, rules):
    _, out = run(graph, rules, review("email"), review("email", "sms"))
    assert len(out.interactions) == 2


def test_message_has_drafts_and_now(graph, rules):
    model, _ = run(graph, rules, review("email", "sms"))
    message = model.seen[0][1].content
    assert "Quick one, Alex" in message and NOW.isoformat() in message


def test_prompt_ends_with_angle(graph, rules):
    model, _ = run(graph, rules, review("email", "sms"))
    assert model.seen[0][0].content.endswith(ANGLE)


def test_changed_payload_is_rejected_then_fixed(graph, rules):
    changed = call(
        "Review",
        interactions=[{**interaction("email"), "payload": {"url": "https://made-up.example"}}, interaction("sms")],
        notes="Added a link.",
    )
    model, out = run(graph, rules, changed, review("email", "sms"))
    assert out.interactions[0].payload is None
    assert "payload" in model.seen[1][-1].content
