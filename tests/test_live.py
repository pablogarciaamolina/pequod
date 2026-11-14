"""Real model calls. Excluded by default; run with: uv run pytest -m live"""

import os
import urllib.request

import pytest
from conftest import load
from langchain_core.tools import tool
from dotenv import load_dotenv

from pequod.agents.base import Agent
from pequod.models.base import build_named
from pequod.types import StopSignal

pytestmark = pytest.mark.live
MODELS = load().models
KEYS = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "huggingface": "HF_TOKEN"}


def skip_if_unavailable(spec):
    load_dotenv()
    key = KEYS.get(spec.provider)
    if key and not spec.get("params", {}).get("local") and not os.environ.get(key):
        pytest.skip(f"{key} is not set")
    if spec.provider == "ollama":
        try:
            tags = urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2).read().decode()
        except OSError:
            pytest.skip("Ollama is not running")
        if spec.name not in tags:
            pytest.skip(f"Ollama model not pulled: ollama pull {spec.name}")


@tool
def note(text: str) -> str:
    """Save a private note. Optional."""
    return "saved"


@pytest.mark.parametrize("name", list(MODELS))
def test_real_model_returns_structured_output(name):
    skip_if_unavailable(MODELS[name])
    agent = Agent(
        name="live",
        model=build_named(MODELS, name),
        system_prompt="You classify one client message. Answer only through the output tool.",
        tools=[note],
        output_type=StopSignal,
        max_steps=3,
    )
    out = agent.invoke('Client message: "Please stop contacting me."')
    assert out.opt_out is True
    assert "stop" in out.evidence.lower()
