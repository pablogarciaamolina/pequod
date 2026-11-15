import importlib

import pytest
from conftest import WRITE, fake
from langchain_core.utils.function_calling import convert_to_openai_tool

from pequod.agents.composer import Composer
from pequod.agents.planner import Planner
from pequod.agents.resolver import Resolver
from pequod.agents.reviewer import Reviewer
from pequod.agents.strategist import Strategist
from pequod.agents.updater import Updater
from pequod.types import Interaction, Paths, Resolution, Review, StopSignal

NAMES = ["strategist", "planner", "composer", "reviewer", "updater", "resolver"]


def test_only_the_updater_has_write_tools(graph, catalog, rules):
    m = fake()
    agents = [
        Strategist(m, graph, max_steps=4, max_paths=2),
        Planner(m, graph, catalog, rules, max_steps=4, max_waves=3, angle=""),
        Composer(m, graph, catalog, rules, max_steps=4, angle=""),
        Reviewer(m, graph, rules, max_steps=4, angle=""),
        Updater(m, graph, max_steps=8),
        Resolver(m, graph, max_steps=4, angle=""),
    ]
    assert [a.name for a in agents] == NAMES
    with_write = [a.name for a in agents if WRITE & {t.name for t in a.tools}]
    assert with_write == ["updater"]


@pytest.mark.parametrize("output_type", [Paths, Interaction, Review, StopSignal, Resolution])
def test_every_output_type_is_a_valid_tool_schema(output_type):
    assert convert_to_openai_tool(output_type)["function"]["parameters"]["properties"]


@pytest.mark.parametrize("name", NAMES)
def test_every_agent_has_a_prompt_constant(name):
    prompt = importlib.import_module(f"pequod.agents.{name}").PROMPT
    assert isinstance(prompt, str) and len(prompt) > 100


@pytest.mark.parametrize("output_type", [Paths, Interaction, Review, StopSignal, Resolution])
def test_every_output_type_has_a_description_for_the_model(output_type):
    assert convert_to_openai_tool(output_type)["function"]["description"].strip()


LIMITS = "- Limits: no pressure, no invented urgency, and never a request for money, passwords or other credentials."


@pytest.mark.parametrize("name", [n for n in NAMES if n != "updater"])  # the Updater writes nothing to the persona
def test_the_limits_are_in_the_prompt_of_every_agent_that_plans_or_writes(name):
    assert importlib.import_module(f"pequod.agents.{name}").PROMPT.count(LIMITS) == 1


@pytest.mark.parametrize("name", NAMES)
def test_prompts_do_not_assume_read_receipts(name):
    assert "ignored" not in importlib.import_module(f"pequod.agents.{name}").PROMPT
