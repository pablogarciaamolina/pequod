"""`pequod graph <run folder>`: open the run's final knowledge graph in an interactive window you can
explore freely — drag nodes, zoom, pan, hover for details. networkx's own drawing is static, so this uses
pyvis (vis.js) to turn the networkx graph into an interactive HTML page."""

import json
from pathlib import Path

import networkx as nx

# node colour by its `kind` (the graph's node type); a default for anything else
KIND_COLOR = {"persona": "#2f5bea", "channel": "#1a7f4b", "interaction": "#6b4fd8", "reply": "#b54708", "fact": "#475467"}
OTHER = "#98a2b3"


def latest_graph(folder: Path) -> dict | None:
    snaps = sorted(folder.glob("graph_*.json"), key=lambda p: int(p.stem.split("_")[1]))
    return json.loads(snaps[-1].read_text(encoding="utf-8")) if snaps else None


def render_graph(folder: str | Path) -> Path:
    """Write an interactive graph.html for the run's final snapshot (self-contained). Returns its path."""
    folder = Path(folder)
    data = latest_graph(folder)
    if data is None:
        raise FileNotFoundError(f"No graph snapshot in {folder} (the run had register off).")

    from pyvis.network import Network  # imported here so a missing dependency is a clean CLI message

    g = nx.node_link_graph(data, edges="edges")
    net = Network(height="820px", width="100%", directed=True, cdn_resources="in_line",
                  notebook=False, bgcolor="#ffffff", font_color="#1c2330")
    net.barnes_hut()  # a physics layout you can drag the nodes around in
    for node in g:
        attrs = g.nodes[node]
        kind = attrs.get("kind", "")
        tip = "\n".join(f"{k}: {v}" for k, v in attrs.items())
        net.add_node(str(node), label=str(attrs.get("name", node)), title=tip,
                     color=KIND_COLOR.get(kind, OTHER), shape="dot", size=24 if kind == "persona" else 15)
    for u, v, d in g.edges(data=True):
        net.add_edge(str(u), str(v), label=d.get("relation", ""), title=d.get("relation", ""))

    out = folder / "graph.html"
    # pyvis's save_graph writes with the platform default encoding (cp1252 on Windows) and fails on the
    # non-ASCII in real messages, so take the HTML string and write it ourselves as UTF-8.
    out.write_text(net.generate_html(notebook=False), encoding="utf-8")
    return out
