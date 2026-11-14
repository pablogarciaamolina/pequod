"""Anthropic provider."""

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel

from pequod.types import ModelSpec


def build(spec: ModelSpec) -> BaseChatModel:
    return ChatAnthropic(model=spec.name, **spec.params)
