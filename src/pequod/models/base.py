"""Common interface: build(spec) -> LangChain chat model."""

import importlib
from collections.abc import Mapping

from langchain_core.language_models import BaseChatModel
from omegaconf import OmegaConf

from pequod.types import ModelSpec

PROVIDERS = ("anthropic", "huggingface", "ollama", "openai", "vllm")  # one file each in this folder


def build(spec: ModelSpec) -> BaseChatModel:
    if spec.provider not in PROVIDERS:
        raise ValueError(f"Unknown provider '{spec.provider}'. Known providers: {', '.join(PROVIDERS)}")
    return importlib.import_module(f"pequod.models.{spec.provider}").build(spec)


def build_named(models: Mapping, name: str) -> BaseChatModel:
    """Build the model called `name` in the `models:` section of the config."""
    if name not in models:
        raise ValueError(f"Unknown model '{name}'. Known models: {', '.join(models)}")
    spec = models[name]
    if OmegaConf.is_config(spec):
        spec = OmegaConf.to_container(spec, resolve=True)  # nested params become plain dicts/lists
    return build(ModelSpec.model_validate(spec))
