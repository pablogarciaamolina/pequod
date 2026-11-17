from conftest import ANGLE, NOW, READ, call, fake, interaction

from pequod.agents.reviewer import Reviewer
from pequod.types import Interaction, Review

DRAFTS = [Interaction(**interaction("pepe")), Interaction(**interaction("stephan", "Quick one, Alex"))]


def review(*channels, notes="Shortened the SMS."):
    return call("Review", interactions=[interaction(c) for c in channels], notes=notes)


def run(graph, rules, *messages):
    model = fake(*messages)
    return model, Reviewer(model, graph, rules, max_steps=4, angle=ANGLE).run(DRAFTS, NOW)


def test_returns_review_with_same_channels(graph, rules):
    _, out = run(graph, rules, review("pepe", "stephan"))
    assert type(out) is Review
    assert [i.channel for i in out.interactions] == ["pepe", "stephan"] and out.notes


def test_tools(graph, rules):
    model, _ = run(graph, rules, review("pepe", "stephan"))
    assert set(model.bound) == READ | {"channel_rules", "Review"}


def test_changed_channel_is_rejected_then_fixed(graph, rules):
    model, out = run(graph, rules, review("pepe", "melina"), review("pepe", "stephan"))
    assert [i.channel for i in out.interactions] == ["pepe", "stephan"]
    assert "Keep the same interactions and channels" in model.seen[1][-1].content


def test_dropped_interaction_is_rejected_then_fixed(graph, rules):
    _, out = run(graph, rules, review("pepe"), review("pepe", "stephan"))
    assert len(out.interactions) == 2


def test_message_has_drafts_and_now(graph, rules):
    model, _ = run(graph, rules, review("pepe", "stephan"))
    message = model.seen[0][1].content
    assert "Quick one, Alex" in message and NOW.isoformat() in message


def test_prompt_ends_with_angle(graph, rules):
    model, _ = run(graph, rules, review("pepe", "stephan"))
    assert model.seen[0][0].content.endswith(ANGLE)


def test_changed_payload_is_rejected_then_fixed(graph, rules):
    changed = call(
        "Review",
        interactions=[{**interaction("pepe"), "payload": {"url": "https://made-up.example"}}, interaction("stephan")],
        notes="Added a link.",
    )
    model, out = run(graph, rules, changed, review("pepe", "stephan"))
    assert out.interactions[0].payload is None
    assert "payload" in model.seen[1][-1].content


def test_body_over_max_length_is_rejected_then_fixed(graph, rules):
    long = call("Review", interactions=[interaction("pepe"), interaction("stephan", "x" * 161)], notes="n")
    model, out = run(graph, rules, long, review("pepe", "stephan"))
    assert len(out.interactions[1].body) <= 160
    error = model.seen[1][-1].content
    assert "161" in error and "160" in error


def test_subject_on_a_channel_without_subject_is_rejected_then_fixed(graph, rules):
    bad = call("Review", interactions=[interaction("pepe"), {**interaction("stephan"), "subject": "Reports"}], notes="n")
    model, out = run(graph, rules, bad, review("pepe", "stephan"))
    assert out.interactions[1].subject is None
    assert "subject" in model.seen[1][-1].content
