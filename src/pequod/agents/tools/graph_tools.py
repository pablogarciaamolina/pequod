"""Graph read tools + write tools (wrap KnowledgeGraph)."""

from typing import Any

from langchain_core.tools import BaseTool, tool

from pequod.graph import KnowledgeGraph, braces


def read_tools(graph: KnowledgeGraph) -> list[BaseTool]:
    @tool
    def graph_summary() -> str:
        """Return every node and edge of the knowledge graph as compact text."""
        return graph.summary()

    @tool
    def find_nodes(query: str) -> str:
        """Find nodes whose id, kind, name or attributes contain the query text."""
        nodes = graph.find_nodes(query)
        return "\n".join(graph.describe(n["id"]) for n in nodes) if nodes else f"No nodes match '{query}'."

    @tool
    def neighbors(node_id: str) -> str:
        """List the nodes connected to a node, with the relation and its direction."""
        try:
            found = graph.neighbors(node_id)
        except ValueError as e:
            return f"Error: {e}"
        arrows = {"out": "-{}->", "in": "<-{}-"}
        lines = [
            f"{arrows[n['direction']].format(n['relation'] + braces(n['attrs']))} {graph.describe(n['node']['id'])}"
            for n in found
        ]
        return "\n".join(lines) if lines else f"Node '{node_id}' has no neighbors."

    return [graph_summary, find_nodes, neighbors]


def write_tools(graph: KnowledgeGraph) -> list[BaseTool]:
    @tool
    def add_node(kind: str, name: str, attrs: dict[str, Any] | None = None) -> str:
        """Create a node for a fact stated by the client or in the input. Returns the new node id."""
        try:
            return graph.add_node(kind, name, attrs)
        except ValueError as e:
            return f"Error: {e}"

    @tool
    def add_edge(source: str, relation: str, target: str, attrs: dict[str, Any] | None = None) -> str:
        """Create an edge between two existing node ids, with a free-text relation."""
        try:
            graph.add_edge(source, relation, target, attrs)
        except ValueError as e:
            return f"Error: {e}"
        return f"Added {source} -{relation}-> {target}"

    @tool
    def update_node(node_id: str, attrs: dict[str, Any]) -> str:
        """Merge attributes into an existing node."""
        try:
            graph.update_node(node_id, attrs)
        except ValueError as e:
            return f"Error: {e}"
        return f"Updated {node_id}"

    return [add_node, add_edge, update_node]
