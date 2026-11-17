import pytest
from conftest import ANGLE, PLATFORM, READ, call, fake, interaction, path, wave

from pequod.agents.base import AgentError
from pequod.agents.composer import Composer
from pequod.types import Interaction, Path

PATH = Path(**path(wave("pepe", "open_door"), wave("stephan", "probe_cause")))


def answer(channel):
    return call("Interaction", **interaction(channel))


def run(graph, catalog, rules, *messages, taken=()):
    model = fake(*messages)
    platforms = {name: PLATFORM[name] for name in rules}
    composer = Composer(model, graph, catalog, rules, platforms, max_steps=4, angle=ANGLE)
    return model, composer.run(PATH, list(taken))


def test_returns_interaction_for_first_wave(graph, catalog, rules):
    model, out = run(graph, catalog, rules, answer("pepe"))
    assert type(out) is Interaction and out.channel == "pepe"
    message = model.seen[0][1].content
    assert "open_door" in message and "probe_cause" not in message


def test_tools(graph, catalog, rules):
    model, _ = run(graph, catalog, rules, answer("pepe"))
    assert set(model.bound) == READ | {"list_strategies", "channel_rules", "Interaction"}


def test_taken_channel_is_rejected_then_fixed(graph, catalog, rules):
    model, out = run(graph, catalog, rules, answer("pepe"), answer("stephan"), taken=["pepe"])
    assert out.channel == "stephan"
    error = model.seen[1][-1].content
    assert "not available" in error and "stephan" in error


def test_unknown_channel_is_rejected_then_fixed(graph, catalog, rules):
    _, out = run(graph, catalog, rules, answer("fax"), answer("stephan"))
    assert out.channel == "stephan"


def test_message_lists_taken_channels(graph, catalog, rules):
    model, _ = run(graph, catalog, rules, answer("stephan"), taken=["pepe"])
    assert "Channels already taken by other paths: pepe" in model.seen[0][1].content


def test_prompt_ends_with_angle(graph, catalog, rules):
    model, _ = run(graph, catalog, rules, answer("pepe"))
    assert model.seen[0][0].content.endswith(ANGLE)


def test_no_free_channel_fails_without_a_model_call(graph, catalog, rules):
    model = fake()
    platforms = {name: PLATFORM[name] for name in rules}
    composer = Composer(model, graph, catalog, rules, platforms, max_steps=4, angle=ANGLE)
    with pytest.raises(AgentError, match="no free channel"):
        composer.run(PATH, list(rules))
    assert model.seen == []


def test_catalog_payload_is_accepted(graph, catalog, rules):
    payload = {"url": "https://example.com/info"}
    _, out = run(graph, catalog, rules, call("Interaction", **interaction("pepe"), payload=payload))
    assert out.payload == payload


def test_invented_payload_is_rejected_then_fixed(graph, catalog, rules):
    invented = call("Interaction", **interaction("pepe"), payload={"url": "https://made-up.example"})
    model, out = run(graph, catalog, rules, invented, answer("pepe"))
    assert out.payload is None
    assert "payload" in model.seen[1][-1].content


def test_catalog_payload_of_another_channel_is_rejected_then_fixed(graph, catalog, rules):
    form = call("Interaction", **interaction("stephan"), payload={"url": "https://forms.example/questions"})
    _, out = run(graph, catalog, rules, form, answer("stephan"))
    assert out.payload is None


def test_body_over_max_length_is_rejected_then_fixed(graph, catalog, rules):
    long = call("Interaction", **interaction("stephan", "x" * 161))
    model, out = run(graph, catalog, rules, long, answer("stephan"))
    assert len(out.body) <= 160
    error = model.seen[1][-1].content
    assert "161" in error and "160" in error


def test_subject_on_a_channel_without_subject_is_rejected_then_fixed(graph, catalog, rules):
    with_subject = call("Interaction", **interaction("stephan"), subject="Reports")
    model, out = run(graph, catalog, rules, with_subject, answer("stephan"))
    assert out.subject is None
    assert "subject" in model.seen[1][-1].content


def test_subject_on_email_is_accepted(graph, catalog, rules):
    _, out = run(graph, catalog, rules, call("Interaction", **interaction("pepe"), subject="Reports"))
    assert out.subject == "Reports"


def test_payload_is_rejected_when_the_platform_disallows_it(graph, catalog):
    from pequod.types import ChannelRules

    rules = {"cto": ChannelRules(max_length=160, subject=False, links_ok=True)}  # an sms-platform instance
    platforms = {"cto": "sms"}
    p = Path(**path(wave("cto", "open_door")))
    form = call("Interaction", **interaction("cto"), payload={"url": "https://forms.example/questions"})  # email-only
    model = fake(form, call("Interaction", **interaction("cto")))
    out = Composer(model, graph, catalog, rules, platforms, max_steps=4, angle=ANGLE).run(p, [])
    assert out.payload is None
