"""OpenAI provider."""

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from pequod.types import ModelSpec


def build(spec: ModelSpec) -> BaseChatModel:
    return ChatOpenAI(model=spec.name, **spec.params)
