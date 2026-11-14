import json
from datetime import datetime, timezone

import pytest

from pequod.graph import KnowledgeGraph


@pytest.fixture
def g():
    graph = KnowledgeGraph()
    graph.add_node("persona", "Alex Carter", {"role": "Ops lead"})
    graph.add_node("channel", "email")
    graph.add_edge("alex_carter", "reachable_via", "email")
    return graph


def test_add_node_returns_slug_id():
    graph = KnowledgeGraph()
    assert graph.add_node("persona", "Alex Carter") == "alex_carter"
    node = graph.node("alex_carter")
    assert node["kind"] == "persona" and node["name"] == "Alex Carter"


def test_add_node_suffixes_on_clash():
    graph = KnowledgeGraph()
    ids = [graph.add_node("reply", "Reply") for _ in range(3)]
    assert ids == ["reply", "reply_2", "reply_3"]


def test_add_node_without_alphanumerics_gets_fallback_id():
    assert KnowledgeGraph().add_node("fact", "!!!") == "node"


def test_add_node_stores_attrs(g):
    assert g.node("alex_carter")["role"] == "Ops lead"


@pytest.mark.parametrize("source, target", [("ghost", "email"), ("email", "ghost")])
def test_add_edge_unknown_node_raises(g, source, target):
    with pytest.raises(ValueError, match="Unknown node 'ghost'"):
        g.add_edge(source, "r", target)


def test_parallel_edges_are_kept(g):
    g.add_edge("alex_carter", "prefers", "email")
    relations = {n["relation"] for n in g.neighbors("alex_carter")}
    assert relations == {"reachable_via", "prefers"}


def test_edge_attrs_are_kept(g):
    g.add_edge("alex_carter", "prefers", "email", {"since": "2026"})
    assert "alex_carter -prefers-> email {since: 2026}" in g.summary()


def test_update_node_merges_attrs(g):
    g.update_node("alex_carter", {"team": "Ops"})
    g.update_node("alex_carter", {"role": "Head of Ops"})
    node = g.node("alex_carter")
    assert node["team"] == "Ops" and node["role"] == "Head of Ops"


def test_update_node_unknown_raises(g):
    with pytest.raises(ValueError, match="Unknown node 'ghost'"):
        g.update_node("ghost", {"a": 1})


def test_find_nodes_matches_kind_name_and_attr_values_case_insensitive(g):
    assert [n["id"] for n in g.find_nodes("OPS")] == ["alex_carter"]
    assert [n["id"] for n in g.find_nodes("persona")] == ["alex_carter"]
    assert [n["id"] for n in g.find_nodes("Carter")] == ["alex_carter"]
    assert g.find_nodes("zzz") == []


def test_neighbors_gives_direction(g):
    out = g.neighbors("alex_carter")[0]
    assert (out["relation"], out["direction"], out["node"]["id"]) == ("reachable_via", "out", "email")
    inc = g.neighbors("email")[0]
    assert (inc["relation"], inc["direction"], inc["node"]["id"]) == ("reachable_via", "in", "alex_carter")


def test_neighbors_unknown_raises(g):
    with pytest.raises(ValueError, match="Unknown node 'ghost'"):
        g.neighbors("ghost")


def test_summary_lists_nodes_and_edges(g):
    summary = g.summary()
    assert "[alex_carter] persona: Alex Carter {role: Ops lead}" in summary
    assert "[email] channel: email" in summary
    assert "alex_carter -reachable_via-> email" in summary


def test_snapshot_writes_json(g, tmp_path):
    path = tmp_path / "run" / "graph_0.json"
    g.snapshot(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert len(data["nodes"]) == 2 and len(data["edges"]) == 1


def test_snapshot_handles_non_json_attrs(g, tmp_path):
    g.update_node("email", {"at": datetime(2026, 11, 16, tzinfo=timezone.utc)})
    g.snapshot(tmp_path / "graph.json")
    assert "2026-11-16" in (tmp_path / "graph.json").read_text(encoding="utf-8")


@pytest.mark.parametrize("key", ["id", "kind", "name"])
def test_reserved_attr_keys_are_rejected(g, key):
    with pytest.raises(ValueError, match="Reserved attribute"):
        g.add_node("fact", "Something", {key: "x"})
    with pytest.raises(ValueError, match="Reserved attribute"):
        g.update_node("alex_carter", {key: "x"})
    assert g.node("alex_carter")["kind"] == "persona"


def test_add_node_keeps_unicode_letters():
    assert KnowledgeGraph().add_node("persona", "Jürgen Müller") == "jürgen_müller"


def test_find_nodes_matches_attr_keys_but_not_reserved_key_names(g):
    assert [n["id"] for n in g.find_nodes("role")] == ["alex_carter"]
    assert g.find_nodes("kind") == []


def test_describe_is_the_summary_line(g):
    assert g.describe("alex_carter") == "[alex_carter] persona: Alex Carter {role: Ops lead}"
    assert g.describe("email") == "[email] channel: email"


def test_neighbors_include_edge_attrs(g):
    g.add_edge("alex_carter", "prefers", "email", {"since": "2026"})
    prefers = [n for n in g.neighbors("alex_carter") if n["relation"] == "prefers"][0]
    assert prefers["attrs"] == {"since": "2026"}


def test_self_loop_shows_in_both_directions(g):
    g.add_edge("email", "same_as", "email")
    directions = [n["direction"] for n in g.neighbors("email") if n["relation"] == "same_as"]
    assert sorted(directions) == ["in", "out"]


def test_add_edge_copies_attrs(g):
    attrs = {"q": 1}
    g.add_edge("alex_carter", "prefers", "email", attrs)
    attrs["q"] = 999
    assert "{q: 1}" in g.summary()
