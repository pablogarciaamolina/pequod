from conftest import NOW, READ, WRITE, call, fake, interaction

from pequod.agents import updater
from pequod.agents.updater import Updater
from pequod.types import Interaction, Reply, StopSignal

SENT = [Interaction(**interaction("whatsapp"))]
REPLIES = [Reply(id="r1", channel="whatsapp", body="Honestly our stock numbers are a day old", received_at=NOW)]


def nothing():
    return call("StopSignal")


OBJECTIVE = "Find out the name of the persona's dog."


def run(graph, *messages, sent=SENT, replies=REPLIES):
    model = fake(*messages)
    return model, Updater(model, graph, max_steps=8).run(sent, replies, OBJECTIVE)


def test_no_new_input_makes_no_model_call(graph):
    model, out = run(graph, sent=[], replies=[])
    assert out == StopSignal() and out.stop is False
    assert model.seen == []


def test_has_read_and_write_tools(graph):
    model, _ = run(graph, nothing())
    assert set(model.bound) == READ | WRITE | {"StopSignal"}


def test_tool_calls_write_into_the_graph(graph):
    run(
        graph,
        call("add_node", kind="reply", name="Reply 1", attrs={"summary": "stock numbers are a day old"}),
        call("add_edge", source="reply_1", relation="received_on", target="personal_whatsapp"),
        nothing(),
    )
    assert graph.node("reply_1")["summary"] == "stock numbers are a day old"
    assert "personal_whatsapp" in {n["node"]["id"] for n in graph.neighbors("reply_1")}


def test_returns_stop_signal_with_evidence(graph):
    _, out = run(graph, call("StopSignal", objective_met=True, evidence="the sync only runs at night"))
    assert out.stop and out.evidence == "the sync only runs at night"


def test_message_has_sent_and_replies(graph):
    model, _ = run(graph, nothing())
    message = model.seen[0][1].content
    assert "which report is slowest" in message and "stock numbers are a day old" in message


def test_message_has_the_objective(graph):
    model, _ = run(graph, nothing())
    assert OBJECTIVE in model.seen[0][1].content


def test_prompt_has_no_angle(graph):
    model, _ = run(graph, nothing())
    assert model.seen[0][0].content == updater.PROMPT


def test_sent_without_replies_still_calls_the_model(graph):
    model, out = run(graph, nothing(), replies=[])
    assert len(model.seen) == 1 and out.stop is False


def test_prompt_does_not_contain_the_hidden_answer():
    text = updater.PROMPT.lower()
    assert not any(word in text for word in ("sync", "night", "warehouse", "stock"))
