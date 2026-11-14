"""KnowledgeGraph: create/modify/query networkx, snapshot. No agent code."""

import json
import pathlib
import re

import networkx as nx

from pequod.types import Engagement


RESERVED = ("id", "kind", "name")


def braces(attrs: dict) -> str:
    return " {" + ", ".join(f"{k}: {v}" for k, v in attrs.items()) + "}" if attrs else ""


class KnowledgeGraph:
    """What we know about the client. Free-form kinds and relations, observed facts only."""

    def __init__(self) -> None:
        self._g = nx.MultiDiGraph()

    @classmethod
    def from_engagement(cls, engagement: Engagement) -> "KnowledgeGraph":
        """Intake: graph v0 = persona node + one node per channel."""
        graph = cls()
        persona = graph.add_node("persona", engagement.persona.name, engagement.persona.features)
        for name, spec in engagement.channels.items():
            channel = graph.add_node("channel", name, {"address": spec.address, **spec.features})
            graph.add_edge(persona, "reachable_via", channel)
        return graph

    # --- write ---

    def add_node(self, kind: str, name: str, attrs: dict | None = None) -> str:
        self._check_attrs(attrs)
        base = re.sub(r"\W+", "_", name.lower()).strip("_") or "node"
        node_id, n = base, 1
        while node_id in self._g:
            n += 1
            node_id = f"{base}_{n}"
        self._g.add_node(node_id)
        self._g.nodes[node_id].update({**(attrs or {}), "kind": kind, "name": name})
        return node_id

    def add_edge(self, source: str, relation: str, target: str, attrs: dict | None = None) -> None:
        self._check(source)
        self._check(target)
        self._g.add_edge(source, target, relation=relation, attrs=dict(attrs or {}))

    def update_node(self, node_id: str, attrs: dict) -> None:
        self._check(node_id)
        self._check_attrs(attrs)
        self._g.nodes[node_id].update(attrs)

    # --- read ---

    def node(self, node_id: str) -> dict:
        self._check(node_id)
        return {**self._g.nodes[node_id], "id": node_id}

    def find_nodes(self, query: str) -> list[dict]:
        q = query.lower()
        nodes = [self.node(n) for n in self._g]
        return [
            n for n in nodes
            if any(q in str(v).lower() or (k not in RESERVED and q in k.lower()) for k, v in n.items())
        ]

    def neighbors(self, node_id: str) -> list[dict]:
        self._check(node_id)
        out = [
            {"relation": d["relation"], "attrs": d["attrs"], "direction": "out", "node": self.node(t)}
            for _, t, d in self._g.out_edges(node_id, data=True)
        ]
        inc = [
            {"relation": d["relation"], "attrs": d["attrs"], "direction": "in", "node": self.node(s)}
            for s, _, d in self._g.in_edges(node_id, data=True)
        ]
        return out + inc

    def describe(self, node_id: str) -> str:
        """One text line for a node: `[id] kind: name {attrs}`."""
        node = self.node(node_id)
        attrs = {k: v for k, v in node.items() if k not in RESERVED}
        return f"[{node_id}] {node['kind']}: {node['name']}{braces(attrs)}"

    def summary(self) -> str:
        lines = [self.describe(n) for n in self._g]
        for s, t, d in self._g.edges(data=True):
            lines.append(f"{s} -{d['relation']}-> {t}{braces(d['attrs'])}")
        return "\n".join(lines)

    # --- snapshot ---

    def to_dict(self) -> dict:
        return nx.node_link_data(self._g, edges="edges")

    def snapshot(self, path: pathlib.Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, default=str), encoding="utf-8")

    def _check(self, node_id: str) -> None:
        if node_id not in self._g:
            raise ValueError(f"Unknown node '{node_id}'. Known nodes: {', '.join(self._g)}")

    @staticmethod
    def _check_attrs(attrs: dict | None) -> None:
        bad = [k for k in attrs or {} if k in RESERVED]
        if bad:
            raise ValueError(f"Reserved attribute keys: {', '.join(bad)}. Use another key.")
