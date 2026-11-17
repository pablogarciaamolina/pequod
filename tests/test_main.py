import logging

import pytest
from conftest import NOW, Clock, FakeOperator, call, fake, interaction, load, path, wave

from pequod import main as cli
from pequod.channels.mock_hub import MockHub

SCRIPT = [
    call("Paths", paths=[path(), path(subgoal="Ask what they tried")]),  # strategist
    call("Paths", paths=[path(wave("pepe")), path(wave("melina"), subgoal="Ask what they tried")]),  # planner
    call("Interaction", **interaction("pepe")),  # composer, path 1
    call("Interaction", **interaction("melina")),  # composer, path 2
    call("Review", interactions=[interaction("pepe"), interaction("melina")], notes="no changes"),
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
    others = [f"agents.{a}.model=claude" for a in ("strategist", "composer", "reviewer", "updater", "resolver")]
    cfg = load(["agents.planner.model=ollama_qwen", "agents.updater.max_steps=6", *others])  # not the config's defaults
    loop = cli.build_loop(cfg, operator(), tmp_path)
    a = loop.agents
    assert [x.max_steps for x in (a.strategist, a.planner, a.composer, a.reviewer, a.updater, a.resolver)] == [8, 8, 12, 8, 6, 8]
    assert set(models) == {"claude", "ollama_qwen"}  # one model object per label
    assert a.planner.model is models["ollama_qwen"] and a.composer.model is a.reviewer.model is models["claude"]
    assert a.strategist.max_paths == cfg.run.max_paths and a.planner.max_waves == cfg.run.max_waves
    assert loop.max_iterations == cfg.run.max_iterations and loop.objective == cfg.engagement.objective
    assert "Conversational angle per channel:" in a.composer.system_prompt


def test_channel_roles_go_into_the_prompts_of_the_agents_that_plan_and_write(models, tmp_path):
    a = cli.build_loop(load(["channels.pepe.role=Sam from Paws and Co"]), operator(), tmp_path).agents
    names = ("strategist", "planner", "composer", "reviewer", "updater", "resolver")
    assert [n for n in names if "- pepe: Sam from Paws and Co" in getattr(a, n).system_prompt] == list(names[:4])
    assert "Conversational angle per channel:" in a.composer.system_prompt


def test_the_channel_list_reaches_the_planning_agents_not_the_updater(models, tmp_path):
    a = cli.build_loop(load(), operator(), tmp_path).agents
    assert "Channels you can send on" in a.planner.system_prompt and "Channels you can send on" in a.composer.system_prompt
    assert "Channels you can send on" not in a.updater.system_prompt and "Channels you can send on" not in a.resolver.system_prompt


def test_angle_block_lists_each_channels_angle(models, tmp_path):
    a = cli.build_loop(load(), operator(), tmp_path).agents
    prompt = a.composer.system_prompt
    assert "Conversational angle per channel:" in prompt
    assert "- pepe:" in prompt and "- stephan:" in prompt          # one block, each channel its own angle
    assert "Conversational angle per channel:" not in a.resolver.system_prompt   # the resolver has no angle


def test_a_missing_angle_file_fails_at_startup(models, tmp_path):
    with pytest.raises(ValueError, match="ghost"):
        cli.build_loop(load(["channels.pepe.angle=ghost"]), operator(), tmp_path)


def test_angle_block_rejects_a_file_without_text(tmp_path):
    (tmp_path / "empty.yaml").write_text("name: empty\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no 'text'"):
        cli.angle_block({"email": "empty"}, tmp_path)


def test_agents_get_only_the_built_system_channels(models, tmp_path):
    loop = cli.build_loop(load(["~channels.stephan"]), operator(), tmp_path)
    assert set(loop.channels) == set(loop.agents.composer.rules) == set(loop.agents.reviewer.rules) == {"pepe", "melina"}


def test_max_paths_larger_than_channels_raises(models, tmp_path):
    with pytest.raises(ValueError, match="max_paths.*4.*3"):
        cli.build_loop(load(["run.max_paths=4"]), operator(), tmp_path)


def test_live_run_with_the_demo_persona_stops_at_startup(models, tmp_path, monkeypatch):
    for variable in ("EMAIL_ADDRESS", "EMAIL_APP_PASSWORD", "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_SMS_FROM", "TWILIO_WHATSAPP_FROM"):
        monkeypatch.setenv(variable, "set")
    with pytest.raises(ValueError, match="placeholder"):
        cli.build_loop(load(["channels=live"]), operator(), tmp_path)


def test_live_run_does_not_touch_the_hub(models, tmp_path, monkeypatch):
    """The hub is the simulator's store: a live run neither clears it nor points it at itself."""
    hub = MockHub("runs/mock_hub.db")
    hub.start_run(tmp_path / "mock-run")
    hub.add_reply("sms", "from the mock run", NOW)
    monkeypatch.setattr(cli, "build_channels", lambda config, persona, hub, clock: {})
    loop = cli.build_loop(load(["channels=live"]), operator(), tmp_path / "live-run")
    assert hub.run_folder() == tmp_path / "mock-run" and len(hub.replies("sms", NOW)) == 1
    assert loop.channels == {} and cli.open_hub(load(["channels=live"])) is None
    assert cli.open_hub(load()) is not None


def test_run_end_to_end_with_fakes(models, caplog, tmp_path):
    cfg = load(["run.max_iterations=1"])
    with caplog.at_level(logging.INFO):
        state = cli.build_loop(cfg, operator(), tmp_path / "run").run()
    assert state["reason"] == "max_iterations" and state["resolution"].report == "THE REPORT"
    assert [m["channel"] for m in MockHub("runs/mock_hub.db").sent()] == ["pepe", "melina"]
    assert "SENT on pepe" in caplog.text and "THE REPORT" in caplog.text
    files = sorted(f.name for f in (tmp_path / "run").iterdir())
    assert files == ["agents.jsonl", "graph_0.json", "graph_1.json", "messages.jsonl", "report.md", "status.json", "trace.jsonl"]


def test_build_loop_starts_a_clean_run(models, tmp_path):
    hub = MockHub("runs/mock_hub.db")
    hub.add_reply("sms", "from the last run", NOW)
    hub.add_command("ok")
    cli.build_loop(load(), operator(), tmp_path / "run")
    assert hub.replies("sms", NOW) == [] and hub.take_commands() == []
    assert hub.run_folder() == tmp_path / "run"


def read_status(folder):
    from pequod.trace import Trace

    return Trace(folder).read_status()


def test_play_returns_0_and_finishes(models, tmp_path):
    assert cli.play(load(["run.max_iterations=1"]), operator(), tmp_path / "run") == 0
    assert read_status(tmp_path / "run").phase == "finished"


def test_a_failing_agent_marks_the_run_as_failed(monkeypatch, tmp_path):
    from langchain_core.messages import AIMessage

    monkeypatch.setattr(cli, "build_named", lambda *_: fake(*[AIMessage("no") for _ in range(4)]))
    assert cli.play(load(), operator(), tmp_path / "run") == 1
    status = read_status(tmp_path / "run")
    assert status.phase == "failed" and "strategist" in status.error and status.wave == 1


def test_a_config_error_is_shown_by_the_simulator(models, tmp_path):
    """The hub must point at the new run even when it fails before it starts."""
    MockHub("runs/mock_hub.db").start_run(tmp_path / "previous")
    assert cli.play(load(["run.max_paths=4"]), operator(), tmp_path / "run") == 1
    assert MockHub("runs/mock_hub.db").run_folder() == tmp_path / "run"
    status = read_status(tmp_path / "run")
    assert status.phase == "failed" and "max_paths" in status.error


def test_ctrl_c_marks_the_run_as_failed(models, tmp_path, monkeypatch):
    def interrupted(*args):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "build_loop", interrupted)
    with pytest.raises(KeyboardInterrupt):
        cli.play(load(), operator(), tmp_path / "run")
    status = read_status(tmp_path / "run")
    assert status.phase == "failed" and "KeyboardInterrupt" in status.error


def test_register_off_keeps_texts_out_of_the_log_file(models, tmp_path):
    """The terminal still shows the messages; the log file of the run does not keep them."""
    import io

    file, console = tmp_path / "main.log", io.StringIO()
    handlers = [logging.FileHandler(file, encoding="utf-8"), logging.StreamHandler(console)]
    root = logging.getLogger()
    level = root.level
    root.setLevel(logging.INFO)
    for handler in handlers:
        root.addHandler(handler)
    try:
        assert cli.play(load(["run.max_iterations=1", "run.register=false"]), operator(), tmp_path / "run") == 0
    finally:
        for handler in handlers:
            root.removeHandler(handler)
            handler.close()
        root.setLevel(level)
    logged = file.read_text(encoding="utf-8")
    assert "Iteration 1" in logged and "Stopped: max_iterations" in logged
    assert all(secret not in logged for secret in ("which report is slowest", "THE REPORT", "Start from the stated symptom"))
    assert "which report is slowest" in console.getvalue() and "THE REPORT" in console.getvalue()
    assert sorted(f.name for f in (tmp_path / "run").iterdir()) == ["status.json"]


def test_register_on_keeps_texts_in_the_log_file(models, tmp_path):
    file = tmp_path / "main.log"
    handler = logging.FileHandler(file, encoding="utf-8")
    root = logging.getLogger()
    level = root.level
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    try:
        cli.play(load(["run.max_iterations=1"]), operator(), tmp_path / "run")
    finally:
        root.removeHandler(handler)
        handler.close()
        root.setLevel(level)
    assert "which report is slowest" in file.read_text(encoding="utf-8")


def test_a_platform_error_stops_the_run_and_names_the_channel(models, tmp_path, monkeypatch, caplog):
    from pequod.channels.base import ChannelError
    from pequod.trace import Trace

    class Broken:
        rules = None
        platform = "email"

        def fetch_replies(self, since):
            raise ChannelError("email: could not read replies: OSError: network is unreachable")

    monkeypatch.setattr(cli, "build_channels", lambda config, persona, hub, clock: {"pepe": Broken()})
    with caplog.at_level(logging.ERROR):
        assert cli.play(load(), operator(), tmp_path / "run") == 1
    status = Trace(tmp_path / "run").read_status()
    assert status.phase == "failed" and status.error.startswith("email: could not read replies")
    assert "Run stopped: email: could not read replies" in caplog.text


def test_register_off_error_does_not_quote_a_library_message(tmp_path):
    from pequod.agents.base import AgentError

    try:
        try:
            raise ValueError("input_value='Hi Alex, your stock numbers'")
        except ValueError as cause:
            raise AgentError(f"planner: ValueError: {cause}") from cause
    except AgentError as e:
        assert cli.brief(e, register=False) == "planner: ValueError"
        assert cli.brief(e, register=True) == str(e)
    plain = AgentError("planner: no valid Paths after 4 model calls (limit 4). Last message: Alex said x")
    assert cli.brief(plain, register=False) == "planner: no valid Paths after 4 model calls (limit 4)."


def test_hub_is_opened_only_when_a_system_channel_is_mock():
    assert cli.open_hub(load(["channels=live"])) is None
    assert cli.open_hub(load(["channels=live", "channels.stephan.mode=mock"])) is not None


def test_build_loop_tells_the_hub_which_channels_the_run_uses(models, tmp_path):
    cli.build_loop(load(["~channels.stephan"]), operator(), tmp_path / "run")
    ch = MockHub("runs/mock_hub.db").channels()
    assert set(ch["system"]) == {"pepe", "melina"}
    assert ch["persona"]["work_email"] == {"platform": "email", "address": "julius.muth@revel8.ai"}


def test_a_run_keeps_what_every_agent_thought_and_did(models, tmp_path):
    loop = cli.build_loop(load(["run.max_iterations=1"]), operator(), tmp_path / "run")
    loop.run()
    runs = loop.trace.agent_runs()
    assert runs[0].agent == "strategist" and runs[-1].agent == "resolver"  # the first update has nothing to absorb
    assert {r.agent for r in runs} == {"updater", "strategist", "planner", "composer", "reviewer", "resolver"}
    strategist = next(r for r in runs if r.agent == "strategist")
    assert strategist.messages[0]["type"] == "system" and strategist.messages[1]["content"].startswith("Objective: ")
