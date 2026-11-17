import json

import pytest

from pequod import main as cli

pytest.importorskip("pyvis")  # pequod graph needs it; skip the module until it is installed
from pequod.visualizations.graph import render_graph


def _run(folder):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "graph_0.json").write_text(json.dumps({
        "directed": True, "multigraph": True, "graph": {},
        "nodes": [{"id": "j", "kind": "persona", "name": "Julius"},
                  {"id": "e", "kind": "channel", "name": "work_email", "platform": "email"}],
        "edges": [{"source": "j", "target": "e", "relation": "reachable_via", "attrs": {}, "key": 0}],
    }), encoding="utf-8")


def test_render_graph_writes_an_interactive_html(tmp_path):
    _run(tmp_path / "run")
    out = render_graph(tmp_path / "run")
    assert out == tmp_path / "run" / "graph.html" and out.is_file()
    text = out.read_text(encoding="utf-8")
    assert "vis" in text and "Julius" in text and "reachable_via" in text  # interactive vis.js graph with our data


def test_render_graph_without_a_snapshot_raises(tmp_path):
    (tmp_path / "bare").mkdir()
    with pytest.raises(FileNotFoundError):
        render_graph(tmp_path / "bare")


def test_graph_command_rejects_a_missing_folder(capsys):
    assert cli.graph(["does-not-exist"]) == 2
    assert "Usage: pequod graph" in capsys.readouterr().err
