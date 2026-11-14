"""Ollama provider."""

from langchain_core.language_models import BaseChatModel
from langchain_ollama import ChatOllama

from pequod.types import ModelSpec


def build(spec: ModelSpec) -> BaseChatModel:
    return ChatOllama(model=spec.name, **spec.params)
