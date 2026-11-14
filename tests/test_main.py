import logging

import pytest
from conftest import Clock, FakeOperator, call, fake, interaction, load, path, wave

from pequod import main as cli
from pequod.channels.mock_hub import MockHub

SCRIPT = [
    call("Paths", paths=[path(), path(subgoal="Ask what they tried")]),  # strategist
    call("Paths", paths=[path(wave("email")), path(wave("whatsapp"), subgoal="Ask what they tried")]),  # planner
    call("Interaction", **interaction("email")),  # composer, path 1
    call("Interaction", **interaction("whatsapp")),  # composer, path 2
    call("Review", interactions=[interaction("email"), interaction("whatsapp")], notes="no changes"),
    call("StopSignal"),  # updater
    call("Resolution", report="THE REPORT"),
]


@pytest.fixture(autouse=True)
def workdir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def models(monkeypatch):
    """Every label gets one fake model; the calls to build_named are recorded."""
    built = {}

    def build_named(_, label):
        built[label] = fake(*SCRIPT)
        return built[label]

    monkeypatch.setattr(cli, "build_named", build_named)
    return built


def operator():
    # build_loop uses the real clock, so the script must end the wait itself: send now, then Enter
    return FakeOperator(Clock(), ["send", "ok"])


def test_build_loop_builds_every_agent_with_its_config(models, tmp_path):
    cfg = load(["agents.planner.model=ollama_qwen", "agents.updater.max_steps=6"])
    loop = cli.build_loop(cfg, operator(), tmp_path)
    a = loop.agents
    assert [x.max_steps for x in (a.strategist, a.planner, a.composer, a.reviewer, a.updater, a.resolver)] == [4, 4, 4, 4, 6, 4]
    assert set(models) == {"claude", "ollama_qwen"}  # one model object per label
    assert a.planner.model is models["ollama_qwen"] and a.composer.model is a.reviewer.model is models["claude"]
    assert a.strategist.max_paths == cfg.run.max_paths and a.planner.max_waves == cfg.run.max_waves
    assert loop.max_iterations == cfg.run.max_iterations and loop.objective == cfg.engagement.objective
    assert a.composer.system_prompt.endswith(cfg.angle.text)


def test_agents_get_only_the_engagement_channels(models, tmp_path):
    cfg = load(["~engagement.channels.sms"])
    loop = cli.build_loop(cfg, operator(), tmp_path)
    assert set(loop.channels) == set(loop.agents.composer.rules) == set(loop.agents.reviewer.rules) == {"email", "whatsapp"}


def test_max_paths_larger_than_channels_raises(models, tmp_path):
    with pytest.raises(ValueError, match="max_paths.*4.*3"):
        cli.build_loop(load(["run.max_paths=4"]), operator(), tmp_path)


def test_live_channels_stop_at_startup(models, tmp_path):
    with pytest.raises(NotImplementedError, match="Stage 6"):
        cli.build_loop(load(["channels=live"]), operator(), tmp_path)


def test_run_end_to_end_with_fakes(models, caplog, tmp_path):
    cfg = load(["run.max_iterations=1"])
    with caplog.at_level(logging.INFO):
        state = cli.build_loop(cfg, operator(), tmp_path / "run").run()
    assert state["reason"] == "max_iterations" and state["resolution"].report == "THE REPORT"
    assert [m["channel"] for m in MockHub("runs/mock_hub.db").sent()] == ["email", "whatsapp"]
    assert "SENT on email" in caplog.text and "THE REPORT" in caplog.text
    files = sorted(f.name for f in (tmp_path / "run").iterdir())
    assert files == ["graph_0.json", "graph_1.json", "report.md", "trace.jsonl"]
