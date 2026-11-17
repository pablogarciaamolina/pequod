import pathlib
import subprocess

import pytest
from conftest import load

from omegaconf import OmegaConf

from pequod.main import CONFIGS
from pequod.types import ChannelRules

ANGLE_DIR = pathlib.Path(CONFIGS) / "angle"


def test_default_config_composes():
    cfg = load()
    assert set(cfg.run) == {"max_iterations", "max_paths", "max_waves", "reply_window_h", "command_poll_s", "register"}
    assert cfg.engagement.persona.name == "Julius Muth"
    assert set(cfg.engagement.channels) == {"work_email", "company_sms", "personal_whatsapp"}
    assert {"plain_message", "direct_ask", "gentle_nudge", "info_link", "call_link", "form_link"} <= set(cfg.strategies)
    assert cfg.agents.updater.max_steps == 16


def test_default_channels_are_mock():
    cfg = load()
    assert set(cfg.channels) == {"pepe", "stephan", "melina"}
    assert all(c.target in cfg.engagement.channels for c in cfg.channels.values())
    assert all(c.mode == "mock" for c in cfg.channels.values())


def test_live_switch_sets_every_channel_live():
    cfg = load(["channels=live"])
    assert all(c.target in cfg.engagement.channels for c in cfg.channels.values())
    assert all(c.mode == "live" for c in cfg.channels.values())
    assert all(len(c.credentials) > 0 for c in cfg.channels.values())


@pytest.mark.parametrize("mode", ["mock", "live"])
def test_every_channel_has_a_role_setting(mode):
    assert all(isinstance(c.role, str) for c in load([f"channels={mode}"]).channels.values())


def test_every_agent_points_to_a_defined_model():
    cfg = load()
    assert set(cfg.agents) == {"strategist", "planner", "composer", "reviewer", "updater", "resolver"}
    assert all(a.model in cfg.models for a in cfg.agents.values())


def test_all_angle_files_have_text():
    files = list(ANGLE_DIR.glob("*.yaml"))
    assert files
    assert all(OmegaConf.load(p).text.strip() for p in files)


@pytest.mark.parametrize("mode", ["mock", "live"])
def test_every_channel_names_an_existing_angle_file(mode):
    for name, ch in load([f"channels={mode}"]).channels.items():
        angle = ch.get("angle")
        assert angle, f"channel '{name}' has no angle"
        assert (ANGLE_DIR / f"{angle}.yaml").is_file(), f"channel '{name}' angle '{angle}' missing"


def test_cli_help_runs():
    out = subprocess.run(["pequod", "--help"], capture_output=True, text=True)
    assert out.returncode == 0


@pytest.mark.parametrize("mode", ["mock", "live"])
def test_channel_rules_validate(mode):
    channels = load([f"channels={mode}"]).channels
    for channel in channels.values():
        ChannelRules.model_validate(dict(channel.rules))
    assert channels.stephan.rules.max_length == 160
    assert channels.pepe.rules.subject is True
    assert channels.stephan.rules.subject is False


def test_channel_rules_are_the_same_in_mock_and_live():
    mock, live = load().channels, load(["channels=live"]).channels
    assert {k: v.rules for k, v in mock.items()} == {k: v.rules for k, v in live.items()}


def test_config_has_mock_hub():
    assert load().mock_hub.endswith("mock_hub.db")


def test_register_is_on_by_default():
    assert load().run.register is True
