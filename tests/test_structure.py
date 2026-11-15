import importlib

import pytest

MODULES = [
    "types", "graph", "strategies", "engagement", "trace", "main",
    "models.base", "models.ollama", "models.vllm", "models.huggingface",
    "models.anthropic", "models.openai",
    "agents.base", "agents.strategist", "agents.planner", "agents.composer",
    "agents.reviewer", "agents.updater", "agents.resolver",
    "agents.tools.graph_tools", "agents.tools.channel_tools", "agents.tools.strategy_tools",
    "channels.base", "channels.email", "channels.sms", "channels.whatsapp", "channels.mock_hub",
]


@pytest.mark.parametrize("name", MODULES)
def test_module_imports(name):
    importlib.import_module(f"pequod.{name}")


def test_engine_does_not_import_the_simulator():
    """One-way dependency: the simulator uses the engine, never the other way round (D46)."""
    import pathlib

    import pequod

    for file in pathlib.Path(pequod.__file__).parent.rglob("*.py"):
        assert "pequod_sim" not in file.read_text(encoding="utf-8"), file
