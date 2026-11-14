"""vLLM provider (OpenAI-compatible server)."""

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from pequod.types import ModelSpec


def build(spec: ModelSpec) -> BaseChatModel:
    if "base_url" not in spec.params:
        raise ValueError("vllm needs params.base_url, e.g. http://localhost:8000/v1")
    return ChatOpenAI(model=spec.name, **{"api_key": "EMPTY", **spec.params})
