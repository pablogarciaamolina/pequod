import pytest
from langchain_core.utils.function_calling import convert_to_openai_tool

from pequod.agents.tools.channel_tools import channel_tools
from pequod.agents.tools.graph_tools import read_tools, write_tools
from pequod.agents.tools.strategy_tools import strategy_tools
from pequod.graph import KnowledgeGraph
from pequod.strategies import StrategyCatalog
from pequod.types import ChannelRules

WRITE = {"add_node", "add_edge", "update_node"}


def by_name(tools):
    return {t.name: t for t in tools}


@pytest.fixture
def graph(engagement):
    return KnowledgeGraph.from_engagement(engagement)


@pytest.fixture
def read(graph):
    return by_name(read_tools(graph))


@pytest.fixture
def write(graph):
    return by_name(write_tools(graph))


@pytest.fixture
def strategies(cfg):
    return by_name(strategy_tools(StrategyCatalog.from_config(cfg.strategies)))


@pytest.fixture
def channels(cfg):
    rules = {name: ChannelRules.model_validate(dict(c.rules)) for name, c in cfg.channels.items()}
    return by_name(channel_tools(rules))


def test_read_tool_names(read):
    assert set(read) == {"graph_summary", "find_nodes", "neighbors"}


def test_write_tool_names(write):
    assert set(write) == WRITE


def test_read_tools_cannot_write(read):
    assert not set(read) & WRITE


def test_every_tool_converts_to_a_model_schema(read, write, strategies, channels):
    for tools in (read, write, strategies, channels):
        for t in tools.values():
            assert convert_to_openai_tool(t)["function"]["description"].strip()
    assert convert_to_openai_tool(read["graph_summary"])["function"]["parameters"]["properties"] == {}


def test_graph_summary_tool_returns_summary(read):
    assert "[alex_carter] persona" in read["graph_summary"].invoke({})


def test_find_nodes_tool(read):
    assert "alex_carter" in read["find_nodes"].invoke({"query": "Northwind"})
    assert read["find_nodes"].invoke({"query": "zzz"}) == "No nodes match 'zzz'."


def test_neighbors_tool(read):
    out = read["neighbors"].invoke({"node_id": "alex_carter"})
    assert "reachable_via" in out and "email" in out


def test_neighbors_tool_unknown_node_returns_error_text(read):
    assert read["neighbors"].invoke({"node_id": "ghost"}).startswith("Error: Unknown node 'ghost'")


def test_add_node_tool_writes_and_returns_id(write, graph):
    out = write["add_node"].invoke(
        {"kind": "fact", "name": "Stale stock data", "attrs": {"quote": "numbers are a day old"}}
    )
    assert out == "stale_stock_data"
    assert graph.node("stale_stock_data")["quote"] == "numbers are a day old"


def test_add_node_tool_attrs_are_optional(write, graph):
    assert write["add_node"].invoke({"kind": "fact", "name": "Manual spreadsheets"}) == "manual_spreadsheets"


def test_add_edge_tool_writes(write, graph):
    write["add_node"].invoke({"kind": "fact", "name": "Spreadsheets"})
    write["add_edge"].invoke({"source": "alex_carter", "relation": "uses", "target": "spreadsheets"})
    assert "uses" in {n["relation"] for n in graph.neighbors("alex_carter")}


def test_add_edge_tool_unknown_node_returns_error_text(write, graph):
    before = graph.summary()
    out = write["add_edge"].invoke({"source": "alex_carter", "relation": "uses", "target": "ghost"})
    assert out.startswith("Error: Unknown node 'ghost'")
    assert graph.summary() == before


def test_update_node_tool_merges(write, graph):
    write["update_node"].invoke({"node_id": "alex_carter", "attrs": {"mood": "frustrated"}})
    node = graph.node("alex_carter")
    assert node["mood"] == "frustrated" and node["org"] == "Northwind Labs"


def test_update_node_tool_unknown_node_returns_error_text(write):
    out = write["update_node"].invoke({"node_id": "ghost", "attrs": {"a": "b"}})
    assert out.startswith("Error: Unknown node 'ghost'")


def test_list_strategies_tool(strategies):
    sms = strategies["list_strategies"].invoke({"channel": "sms"})
    assert "plain_message" in sms and "booking_link" in sms and "intake_form" not in sms
    assert "https://cal.example/alex" in sms
    everything = strategies["list_strategies"].invoke({})
    assert all(s in everything for s in ("plain_message", "kb_link", "booking_link", "intake_form"))


def test_list_strategies_unknown_channel_returns_error_text(strategies):
    out = strategies["list_strategies"].invoke({"channel": "fax"})
    assert out.startswith("Error:") and "email" in out


def test_channel_rules_tool(channels):
    assert "160" in channels["channel_rules"].invoke({"channel": "sms"})


def test_channel_rules_unknown_channel_returns_error_text(channels):
    out = channels["channel_rules"].invoke({"channel": "fax"})
    assert out.startswith("Error:") and "email, sms, whatsapp" in out


def test_add_node_tool_reserved_key_returns_error_text(write, graph):
    out = write["add_node"].invoke({"kind": "fact", "name": "X", "attrs": {"kind": "y"}})
    assert out.startswith("Error: Reserved attribute")


def test_find_nodes_tool_uses_the_summary_format(read):
    assert "[email] channel: email {address: alex@northwind.example" in read["find_nodes"].invoke({"query": "email"})


def test_neighbors_tool_shows_edge_attrs(read, write):
    write["add_edge"].invoke(
        {"source": "alex_carter", "relation": "prefers", "target": "email", "attrs": {"since": "2026"}}
    )
    assert "-prefers {since: 2026}-> [email]" in read["neighbors"].invoke({"node_id": "alex_carter"})
