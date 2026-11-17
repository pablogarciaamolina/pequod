import pytest

from pequod.graph import KnowledgeGraph


@pytest.fixture
def graph(engagement):
    return KnowledgeGraph.from_engagement(engagement)


def test_graph_v0_has_persona_and_channel_nodes(graph):
    assert {n["id"] for n in graph.to_dict()["nodes"]} == {"julius_muth", "work_email", "company_sms", "personal_whatsapp"}


def test_persona_node_carries_features(graph):
    node = graph.node("julius_muth")
    assert node["kind"] == "persona" and node["org"] == "Revel8"


def test_channel_node_carries_address_and_features(graph):
    node = graph.node("work_email")
    assert node["kind"] == "channel"
    assert node["address"] == "julius.muth@revel8.ai" and node["hours"] == "any time" and node["platform"] == "email"


def test_persona_reachable_via_every_channel(graph):
    neighbors = graph.neighbors("julius_muth")
    assert {n["node"]["id"] for n in neighbors} == {"work_email", "company_sms", "personal_whatsapp"}
    assert all(n["relation"] == "reachable_via" and n["direction"] == "out" for n in neighbors)


def test_objective_not_in_graph(graph):
    assert "Surface" not in graph.summary()
