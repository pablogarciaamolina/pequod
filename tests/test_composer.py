import pytest
from conftest import ANGLE, READ, call, fake, interaction, path, wave

from pequod.agents.base import AgentError
from pequod.agents.composer import Composer
from pequod.types import Interaction, Path

PATH = Path(**path(wave("email", "open_door"), wave("sms", "probe_cause")))


def answer(channel):
    return call("Interaction", **interaction(channel))


def run(graph, catalog, rules, *messages, taken=()):
    model = fake(*messages)
    composer = Composer(model, graph, catalog, rules, max_steps=4, angle=ANGLE)
    return model, composer.run(PATH, list(taken))


def test_returns_interaction_for_first_wave(graph, catalog, rules):
    model, out = run(graph, catalog, rules, answer("email"))
    assert type(out) is Interaction and out.channel == "email"
    message = model.seen[0][1].content
    assert "open_door" in message and "probe_cause" not in message


def test_tools(graph, catalog, rules):
    model, _ = run(graph, catalog, rules, answer("email"))
    assert set(model.bound) == READ | {"list_strategies", "channel_rules", "Interaction"}


def test_taken_channel_is_rejected_then_fixed(graph, catalog, rules):
    model, out = run(graph, catalog, rules, answer("email"), answer("sms"), taken=["email"])
    assert out.channel == "sms"
    error = model.seen[1][-1].content
    assert "not available" in error and "sms" in error


def test_unknown_channel_is_rejected_then_fixed(graph, catalog, rules):
    _, out = run(graph, catalog, rules, answer("fax"), answer("sms"))
    assert out.channel == "sms"


def test_message_lists_taken_channels(graph, catalog, rules):
    model, _ = run(graph, catalog, rules, answer("sms"), taken=["email"])
    assert "Channels already taken by other paths: email" in model.seen[0][1].content


def test_prompt_ends_with_angle(graph, catalog, rules):
    model, _ = run(graph, catalog, rules, answer("email"))
    assert model.seen[0][0].content.endswith(ANGLE)


def test_no_free_channel_fails_without_a_model_call(graph, catalog, rules):
    model = fake()
    composer = Composer(model, graph, catalog, rules, max_steps=4, angle=ANGLE)
    with pytest.raises(AgentError, match="no free channel"):
        composer.run(PATH, list(rules))
    assert model.seen == []


def test_catalog_payload_is_accepted(graph, catalog, rules):
    payload = {"url": "https://kb.example/erp-sync"}
    _, out = run(graph, catalog, rules, call("Interaction", **interaction("email"), payload=payload))
    assert out.payload == payload


def test_invented_payload_is_rejected_then_fixed(graph, catalog, rules):
    invented = call("Interaction", **interaction("email"), payload={"url": "https://made-up.example"})
    model, out = run(graph, catalog, rules, invented, answer("email"))
    assert out.payload is None
    assert "payload" in model.seen[1][-1].content


def test_catalog_payload_of_another_channel_is_rejected_then_fixed(graph, catalog, rules):
    form = call("Interaction", **interaction("sms"), payload={"url": "https://forms.example/intake"})
    _, out = run(graph, catalog, rules, form, answer("sms"))
    assert out.payload is None
