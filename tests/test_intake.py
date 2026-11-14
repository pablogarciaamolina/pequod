import pytest

from pequod.graph import KnowledgeGraph


@pytest.fixture
def graph(engagement):
    return KnowledgeGraph.from_engagement(engagement)


def test_graph_v0_has_persona_and_channel_nodes(graph):
    assert {n["id"] for n in graph.to_dict()["nodes"]} == {"alex_carter", "email", "sms", "whatsapp"}


def test_persona_node_carries_features(graph):
    node = graph.node("alex_carter")
    assert node["kind"] == "persona" and node["org"] == "Northwind Labs"


def test_channel_node_carries_address_and_features(graph):
    node = graph.node("email")
    assert node["kind"] == "channel"
    assert node["address"] == "alex@northwind.example" and node["hours"] == "09-12"


def test_persona_reachable_via_every_channel(graph):
    neighbors = graph.neighbors("alex_carter")
    assert {n["node"]["id"] for n in neighbors} == {"email", "sms", "whatsapp"}
    assert all(n["relation"] == "reachable_via" and n["direction"] == "out" for n in neighbors)


def test_objective_not_in_graph(graph):
    assert "Surface" not in graph.summary()
