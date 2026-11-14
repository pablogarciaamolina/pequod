import importlib
import re

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from omegaconf import OmegaConf
from langchain_anthropic import ChatAnthropic
from langchain_huggingface import ChatHuggingFace
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI

from pequod.models import base, huggingface
from pequod.models.base import PROVIDERS, build, build_named
from pequod.types import ModelSpec


@pytest.fixture(autouse=True)
def keys(monkeypatch):
    for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "HF_TOKEN"):
        monkeypatch.setenv(key, "x")


@pytest.mark.parametrize(
    "provider, params, cls, attr",
    [
        ("anthropic", {}, ChatAnthropic, "model"),
        ("ollama", {}, ChatOllama, "model"),
        ("openai", {}, ChatOpenAI, "model_name"),
        ("vllm", {"base_url": "http://localhost:8000/v1"}, ChatOpenAI, "model_name"),
        ("huggingface", {}, ChatHuggingFace, "model_id"),
    ],
)
def test_build_returns_the_provider_chat_model(provider, params, cls, attr):
    model = build(ModelSpec(provider=provider, name="org/m", params=params))
    assert isinstance(model, cls)
    assert getattr(model, attr) == "org/m"


def test_params_are_passed_to_the_model():
    model = build(ModelSpec(provider="ollama", name="m", params={"temperature": 0.2}))
    assert model.temperature == 0.2


def test_vllm_needs_base_url():
    with pytest.raises(ValueError, match="base_url"):
        build(ModelSpec(provider="vllm", name="m"))


def test_unknown_provider_raises():
    with pytest.raises(ValueError, match="Unknown provider 'nope'.*ollama"):
        build(ModelSpec(provider="nope", name="m"))


@pytest.mark.parametrize("provider", PROVIDERS)
def test_every_provider_has_a_module(provider):
    assert callable(importlib.import_module(f"pequod.models.{provider}").build)


def test_huggingface_local_needs_a_known_family():
    for params in ({"local": True}, {"local": True, "family": "gpt"}):
        with pytest.raises(ValueError, match="family.*llama.*mistral.*qwen"):
            build(ModelSpec(provider="huggingface", name="org/m", params=params))


def test_huggingface_local_loads_the_weights_by_name(monkeypatch):
    seen = {}

    class Pipeline:
        @classmethod
        def from_model_id(cls, **kwargs):
            seen.update(kwargs)
            return "llm"

    monkeypatch.setattr(huggingface, "HuggingFacePipeline", Pipeline)
    monkeypatch.setattr(huggingface, "Chat", lambda llm, family=None: ("chat", llm, family))
    spec = ModelSpec(provider="huggingface", name="org/m", params={"local": True, "family": "qwen", "device": 0})
    assert build(spec) == ("chat", "llm", "qwen")
    assert seen == {"model_id": "org/m", "task": "text-generation", "device": 0}


# --- local Hugging Face weights: tools go into the prompt and tool calls are read from the text ---

CALL = {"name": "find_nodes", "args": {"query": "stock"}}
TEXTS = {
    "qwen": '<tool_call>\n{"name": "find_nodes", "arguments": {"query": "stock"}}\n</tool_call>',
    "llama": '{"name": "find_nodes", "parameters": {"query": "stock"}}',
    "mistral": '[{"name": "find_nodes", "arguments": {"query": "stock"}}]',
}


@pytest.mark.parametrize("family", list(TEXTS))
def test_parse_reads_the_tool_call_of_each_family(family):
    assert huggingface.parse(family, TEXTS[family]) == [CALL]


@pytest.mark.parametrize(
    "family, text",
    [("llama", '<|python_tag|>{"name": "find_nodes", "parameters": {"query": "stock"}}'),
     ("mistral", '[TOOL_CALLS] [{"name": "find_nodes", "arguments": {"query": "stock"}}]')],
)
def test_parse_accepts_the_marker_token_when_it_is_kept(family, text):
    assert huggingface.parse(family, text) == [CALL]


def test_parse_reads_several_qwen_calls():
    assert huggingface.parse("qwen", "thinking...\n" + TEXTS["qwen"] + "\n" + TEXTS["qwen"]) == [CALL, CALL]


@pytest.mark.parametrize("family", list(TEXTS))
@pytest.mark.parametrize("text", ["Hello, how can I help?", '{"name": "x"', '{"a": 1}', '[1, 2]', '"text"', ""])
def test_parse_returns_nothing_for_plain_or_broken_text(family, text):
    assert huggingface.parse(family, text) == []


class Tokenizer:
    def __init__(self):
        self.seen = {}

    def apply_chat_template(self, messages, **kwargs):
        self.seen = {"messages": messages, **kwargs}
        return "PROMPT"


class Pipeline:
    task = "text-generation"

    def __init__(self, text):
        self.text, self.seen = text, None

    def __call__(self, prompts, **kwargs):
        self.seen = (prompts, kwargs)
        return [[{"generated_text": self.text}]]


def local(family, text):
    tokenizer, pipeline = Tokenizer(), Pipeline(text)
    llm = huggingface.HuggingFacePipeline(pipeline=pipeline, model_id="org/m")
    return huggingface.Chat(llm=llm, tokenizer=tokenizer, family=family), tokenizer, pipeline


@pytest.mark.parametrize("family", list(TEXTS))
def test_local_model_returns_tool_calls(family):
    model, tokenizer, pipeline = local(family, TEXTS[family])
    out = model.bind_tools([one, two], tool_choice="any").invoke("hi")
    assert [(c["name"], c["args"]) for c in out.tool_calls] == [("find_nodes", {"query": "stock"})]
    assert out.content == ""
    assert re.fullmatch("[a-z0-9]{9}", out.tool_calls[0]["id"])  # Mistral templates require this id shape
    assert [t["function"]["name"] for t in tokenizer.seen["tools"]] == ["one", "two"]
    assert tokenizer.seen["add_generation_prompt"] is True and tokenizer.seen["tokenize"] is False
    assert pipeline.seen == (["PROMPT"], {"return_full_text": False})


def test_local_model_without_tools_returns_text():
    model, tokenizer, _ = local("qwen", " " + TEXTS["qwen"] + " ")
    out = model.invoke("hi")
    assert out.tool_calls == [] and out.content == TEXTS["qwen"]
    assert tokenizer.seen["tools"] is None


def test_local_model_plain_answer_stays_text():
    model, _, _ = local("llama", "I cannot help with that.")
    out = model.bind_tools([one]).invoke("hi")
    assert out.tool_calls == [] and out.content == "I cannot help with that."


def test_local_prompt_gets_earlier_tool_calls_and_results():
    model, tokenizer, _ = local("qwen", "done")
    model.invoke(
        [
            SystemMessage("sys"),
            HumanMessage("hi"),
            AIMessage("", tool_calls=[{"name": "one", "args": {"a": 1}, "id": "abc123def"}]),
            ToolMessage("1", tool_call_id="abc123def", name="one"),
        ]
    )
    assert tokenizer.seen["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "abc123def", "type": "function", "function": {"name": "one", "arguments": {"a": 1}}}],
        },
        {"role": "tool", "name": "one", "tool_call_id": "abc123def", "content": "1"},
    ]


def test_mistral_system_prompt_is_merged_into_the_first_user_message():
    """Mistral templates drop the system message after a tool round."""
    model, tokenizer, _ = local("mistral", "done")
    model.invoke([SystemMessage("sys"), HumanMessage("hi")])
    assert tokenizer.seen["messages"] == [{"role": "user", "content": "sys\n\nhi"}]


def test_a_local_model_drives_a_real_agent():
    from pequod.agents.base import Agent
    from pequod.types import StopSignal

    text = '<tool_call>\n{"name": "StopSignal", "arguments": {"opt_out": true, "evidence": "stop"}}\n</tool_call>'
    model, _, _ = local("qwen", text)
    out = Agent("a", model, "sys", [one], StopSignal, max_steps=2).invoke("Client: stop")
    assert out.opt_out is True and out.evidence == "stop"


def test_config_models_are_valid_specs(cfg):
    for spec in cfg.models.values():
        assert ModelSpec.model_validate(dict(spec)).provider in PROVIDERS


def test_build_named_uses_the_config(cfg):
    model = build_named(cfg.models, "ollama_qwen")
    assert isinstance(model, ChatOllama) and model.model == "qwen2.5:14b"


def test_build_named_unknown_model_raises(cfg):
    with pytest.raises(ValueError, match="Unknown model 'nope'.*ollama_qwen"):
        build_named(cfg.models, "nope")


def test_every_agent_model_can_be_built(cfg):
    for agent in cfg.agents.values():
        build_named(cfg.models, agent.model)


@tool
def one() -> str:
    """One."""
    return "1"


@tool
def two() -> str:
    """Two."""
    return "2"


@pytest.mark.parametrize(
    "provider, params",
    [("anthropic", {}), ("ollama", {}), ("openai", {}), ("vllm", {"base_url": "http://localhost:8000/v1"}), ("huggingface", {})],
)
def test_every_provider_accepts_the_agent_tool_binding(provider, params):
    """create_agent binds several tools with tool_choice="any"; a provider must not reject that."""
    build(ModelSpec(provider=provider, name="org/m", params=params)).bind_tools([one, two], tool_choice="any")


def test_nested_params_become_plain_python(monkeypatch):
    seen = []
    monkeypatch.setattr(base, "build", seen.append)
    models = OmegaConf.create({"m": {"provider": "ollama", "name": "x", "params": {"model_kwargs": {"a": [1]}}}})
    build_named(models, "m")
    kwargs = seen[0].params["model_kwargs"]
    assert type(kwargs) is dict and type(kwargs["a"]) is list
