"""`pequod report <run folder>`: a self-contained HTML page for one run — the knowledge graph drawn,
the wave timeline, every agent's reasoning, and the final report. No network, no CDN: the graph is laid
out with networkx and emitted as inline SVG."""

import html
import json
from pathlib import Path

import networkx as nx
from omegaconf import OmegaConf

from pequod.trace import Trace

WIDTH, HEIGHT, MARGIN = 960, 600, 60
# node fill by its `kind` (the graph's node type, free text); a sensible default for anything else
KIND_COLOR = {"persona": "#2f5bea", "channel": "#1a7f4b", "interaction": "#6b4fd8", "reply": "#b54708", "fact": "#475467"}
OTHER = "#98a2b3"


def esc(text: object) -> str:
    return html.escape(str(text), quote=True)


def objective(folder: Path) -> str:
    cfg = folder / ".hydra" / "config.yaml"
    if cfg.is_file():
        try:
            return str(OmegaConf.load(cfg).engagement.objective)
        except Exception:
            pass
    return ""


def latest_graph(folder: Path) -> dict | None:
    snaps = sorted(folder.glob("graph_*.json"), key=lambda p: int(p.stem.split("_")[1]))
    return json.loads(snaps[-1].read_text(encoding="utf-8")) if snaps else None


def graph_svg(data: dict) -> str:
    """The graph as inline SVG: nodes coloured by kind, edges labelled with their relation. Positions
    from networkx's spring layout (fixed seed, so a run always draws the same)."""
    g = nx.node_link_graph(data, edges="edges")
    if g.number_of_nodes() == 0:
        return "<p class='muted'>The graph is empty.</p>"
    pos = nx.spring_layout(g, seed=1, k=1.1 / max(1, g.number_of_nodes() ** 0.5))
    xs = [p[0] for p in pos.values()] or [0]
    ys = [p[1] for p in pos.values()] or [0]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)

    def place(p):
        x = MARGIN + (p[0] - minx) / (maxx - minx or 1) * (WIDTH - 2 * MARGIN)
        y = MARGIN + (p[1] - miny) / (maxy - miny or 1) * (HEIGHT - 2 * MARGIN)
        return x, y

    xy = {n: place(p) for n, p in pos.items()}
    parts = [
        f'<svg viewBox="0 0 {WIDTH} {HEIGHT}" class="graph" xmlns="http://www.w3.org/2000/svg">',
        '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
        'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#c0c6d0"/></marker></defs>',
    ]
    for u, v, d in g.edges(data=True):
        (x1, y1), (x2, y2) = xy[u], xy[v]
        parts.append(f'<line x1="{x1:.0f}" y1="{y1:.0f}" x2="{x2:.0f}" y2="{y2:.0f}" stroke="#d7dbe3" '
                     f'stroke-width="1.5" marker-end="url(#arrow)"/>')
        rel = d.get("relation", "")
        if rel:
            parts.append(f'<text x="{(x1 + x2) / 2:.0f}" y="{(y1 + y2) / 2 - 3:.0f}" class="edge-label">{esc(rel)}</text>')
    for node, (x, y) in xy.items():
        attrs = g.nodes[node]
        kind = attrs.get("kind", "")
        name = attrs.get("name", node)
        colour = KIND_COLOR.get(kind, OTHER)
        r = 16 if kind == "persona" else 11
        tip = "\n".join(f"{k}: {v}" for k, v in attrs.items())
        label = esc(name if len(str(name)) <= 28 else str(name)[:27] + "…")
        parts.append(f'<g class="node"><title>{esc(tip)}</title>'
                     f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{r}" fill="{colour}"/>'
                     f'<text x="{x:.0f}" y="{y + r + 12:.0f}" class="node-label">{label}</text></g>')
    parts.append("</svg>")
    legend = " ".join(
        f'<span class="chip"><i style="background:{c}"></i>{esc(k)}</span>' for k, c in KIND_COLOR.items()
    )
    return f'<div class="legend">{legend}</div>' + "".join(parts)


def turn_html(message: dict) -> str:
    """One message of an agent's loop as a labelled block."""
    kind = message.get("type", "")
    label = {"system": "system prompt", "human": "input", "ai": "model", "tool": f"tool result · {message.get('name', '')}"}.get(kind, kind)
    rows = []
    if message.get("reasoning"):
        rows.append(f'<div class="reasoning">{esc(message["reasoning"])}</div>')
    if message.get("content"):
        rows.append(f'<pre>{esc(message["content"])}</pre>')
    for call in message.get("tool_calls", []):
        rows.append(f'<div class="call">→ {esc(call.get("name", ""))}({esc(json.dumps(call.get("args", {})))})</div>')
    body = "".join(rows) or '<div class="muted">(empty)</div>'
    return f'<div class="turn {esc(kind)}"><div class="turn-label">{esc(label)}</div>{body}</div>'


def agents_html(runs) -> str:
    if not runs:
        return "<p class='muted'>No agent runs recorded (the run had register off).</p>"
    out = []
    for i, run in enumerate(runs):
        flag = ' <span class="bad">· failed</span>' if run.error else ""
        turns = "".join(turn_html(m) for m in run.messages)
        err = f'<div class="error">{esc(run.error)}</div>' if run.error else ""
        out.append(f'<details class="agent"><summary>{i + 1}. {esc(run.agent)}{flag}</summary>{err}{turns}</details>')
    return "".join(out)


def wave_html(record) -> str:
    def items(title, rows):
        inner = "".join(f"<li>{r}</li>" for r in rows) or '<li class="muted">(none)</li>'
        return f"<h4>{esc(title)}</h4><ul>{inner}</ul>"

    paths = [esc(p) for p in record.paths]
    sent = [f'<span class="meta">{esc(i.channel)} · {esc(i.text)}{"…" if i.cut else ""}</span>' for i in record.interactions]
    replies = [f'<span class="meta">{esc(r.channel)}</span> “{esc(r.body)}”' for r in record.replies]
    flags = ", ".join(f for f in ("objective_met", "solution_accepted", "opt_out") if getattr(record.stop_signal, f)) or "none"
    evid = f' · “{esc(record.stop_signal.evidence)}”' if record.stop_signal.evidence else ""
    decision = f'stop ({esc(record.reason)})' if record.reason else "continue"
    cls = "stop" if record.reason else "go"
    return (f'<div class="card"><h3>Wave {record.wave}</h3><div class="from">planned from {esc(record.snapshot)}</div>'
            f'{items("Paths", paths)}{items("Sent", sent)}{items("Replies absorbed", replies)}'
            f'<h4>Stop signal</h4><div>{esc(flags)}{evid}</div>'
            f'<span class="decision {cls}">Decision: {decision}</span></div>')


def build_html(folder: Path) -> str:
    trace = Trace(folder)
    data = latest_graph(folder)
    graph = graph_svg(data) if data else "<p class='muted'>No graph snapshot (the run had register off).</p>"
    waves = "".join(wave_html(r) for r in trace.records()) or "<p class='muted'>No finished wave.</p>"
    report = trace.read_report()
    report_block = f'<div class="report"><pre>{esc(report)}</pre></div>' if report else "<p class='muted'>No report.</p>"
    obj = objective(folder)
    obj_block = f'<p class="objective"><b>Objective:</b> {esc(obj)}</p>' if obj else ""
    return PAGE.format(folder=esc(folder), objective=obj_block, graph=graph, report=report_block,
                       waves=waves, agents=agents_html(trace.agent_runs()))


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pequod run report</title>
<style>
  :root {{ --ink:#1c2330; --soft:#667085; --line:#e2e5ea; --bg:#f4f5f7; --panel:#fff; --accent:#2f5bea; --bad:#b42318; }}
  * {{ box-sizing:border-box; }}
  body {{ font:14px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; color:var(--ink); background:var(--bg); margin:0; padding:24px; }}
  h1 {{ font-size:20px; margin:0 0 2px; }} h2 {{ font-size:16px; margin:28px 0 10px; }}
  h3 {{ font-size:14px; margin:0 0 2px; }} h4 {{ font-size:11px; letter-spacing:.06em; text-transform:uppercase; color:var(--soft); margin:10px 0 3px; }}
  .wrap {{ max-width:1000px; margin:0 auto; }}
  .folder {{ color:var(--soft); font-size:12px; }} .objective {{ margin:8px 0 0; }}
  .muted {{ color:var(--soft); }} .bad {{ color:var(--bad); }}
  .panel {{ background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:16px; margin-top:10px; }}
  .graph {{ width:100%; height:auto; background:var(--panel); border-radius:10px; }}
  .legend {{ margin-bottom:8px; }} .chip {{ font-size:12px; color:var(--soft); margin-right:12px; }}
  .chip i {{ display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:4px; vertical-align:middle; }}
  .edge-label {{ fill:var(--soft); font-size:9px; text-anchor:middle; }}
  .node-label {{ fill:var(--ink); font-size:11px; text-anchor:middle; }}
  .cards {{ display:grid; gap:12px; grid-template-columns:repeat(auto-fill,minmax(300px,1fr)); }}
  .card {{ border:1px solid var(--line); border-radius:10px; padding:12px 14px; background:var(--panel); }}
  .card .from {{ font-size:11px; color:var(--soft); }} .card ul {{ margin:0; padding-left:18px; }} .card li {{ overflow-wrap:anywhere; }}
  .meta {{ color:var(--soft); }}
  .decision {{ display:inline-block; margin-top:10px; padding:2px 10px; border-radius:10px; font-size:12px; font-weight:600; background:var(--bg); color:var(--soft); }}
  .decision.stop {{ background:#fde8e6; color:var(--bad); }}
  .report pre, .turn pre {{ white-space:pre-wrap; overflow-wrap:anywhere; margin:4px 0; }}
  .report {{ border:1px solid #b7e0c7; background:#f1faf4; border-radius:10px; padding:12px 14px; }}
  details.agent {{ border:1px solid var(--line); border-radius:10px; background:var(--panel); margin-bottom:8px; padding:4px 12px; }}
  details.agent summary {{ cursor:pointer; font-weight:600; padding:6px 0; }}
  .turn {{ border-left:3px solid var(--line); padding:4px 0 4px 10px; margin:8px 0; }}
  .turn.ai {{ border-color:var(--accent); }} .turn.tool {{ border-color:#1a7f4b; }} .turn.system {{ border-color:var(--soft); }}
  .turn-label {{ font-size:11px; letter-spacing:.05em; text-transform:uppercase; color:var(--soft); }}
  .reasoning {{ color:var(--soft); font-style:italic; white-space:pre-wrap; margin:4px 0; }}
  .call {{ font-family:ui-monospace,Menlo,Consolas,monospace; font-size:12px; color:var(--accent); overflow-wrap:anywhere; }}
  .error {{ color:var(--bad); font-weight:600; }}
  pre {{ font-family:ui-monospace,Menlo,Consolas,monospace; font-size:12.5px; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --ink:#e6e9ef; --soft:#9aa3b2; --line:#2a2f3a; --bg:#14171d; --panel:#1b1f27; }}
    .report {{ border-color:#1f5137; background:#11261b; }} .decision.stop {{ background:#3a1b1b; }}
  }}
</style></head>
<body><div class="wrap">
  <h1>Pequod run report</h1>
  <div class="folder">{folder}</div>
  {objective}
  <h2>Knowledge graph (final state)</h2>
  <div class="panel">{graph}</div>
  <h2>Report for the supervisor</h2>
  {report}
  <h2>Waves</h2>
  <div class="cards">{waves}</div>
  <h2>Agent reasoning</h2>
  {agents}
</div></body></html>
"""


def write_report(folder: str | Path) -> Path:
    folder = Path(folder)
    out = folder / "report.html"
    out.write_text(build_html(folder), encoding="utf-8")
    return out
