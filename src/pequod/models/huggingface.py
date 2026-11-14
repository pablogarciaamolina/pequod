"""Hugging Face provider: hosted Inference API, or local weights with params.local = true.

Hosted: the server writes the tools into the prompt and returns tool calls.
Local: there is no server, so `Chat` does both. The tokenizer's own chat template writes the tools into
the prompt; `parse` reads the tool calls back from the generated text. Each model family writes tool
calls differently, so local models need `params.family`:

    qwen     <tool_call>{"name": ..., "arguments": {...}}</tool_call>   several calls per step
    llama    {"name": ..., "parameters": {...}}                         one call per step
    mistral  [{"name": ..., "arguments": {...}}]                        several calls per step

Checked models are listed in README.md.
"""

import json
import re
import uuid

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_huggingface import ChatHuggingFace, HuggingFaceEndpoint, HuggingFacePipeline

from pequod.types import ModelSpec

# family -> (texts that may hold tool calls, key of the arguments)
FAMILIES = {
    "qwen": (lambda text: re.findall(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", text, re.DOTALL), "arguments"),
    "llama": (lambda text: [text.replace("<|python_tag|>", "")], "parameters"),
    "mistral": (lambda text: [text.replace("[TOOL_CALLS]", "")], "arguments"),
}
ROLES = {"system": "system", "human": "user", "ai": "assistant", "tool": "tool"}


def parse(family: str, text: str) -> list[dict]:
    """Tool calls ({"name", "args"}) found in the text a local model generated; [] if there are none."""
    find, key = FAMILIES[family]
    calls = []
    for chunk in find(text):
        try:
            found = json.loads(chunk)
        except ValueError:
            return []
        for call in found if isinstance(found, list) else [found]:
            if not (isinstance(call, dict) and isinstance(call.get("name"), str) and isinstance(call.get(key), dict)):
                return []
            calls.append({"name": call["name"], "args": call[key]})
    return calls


class Chat(ChatHuggingFace):
    family: str | None = None  # set for local weights only

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        # ChatHuggingFace rejects tool_choice when several tools are bound, which is what agents do.
        return super().bind_tools(tools, **kwargs)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        if self.family is None:
            return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
        tools = kwargs.get("tools")
        prompt = self.tokenizer.apply_chat_template(
            self._dicts(messages), tools=tools, tokenize=False, add_generation_prompt=True
        )
        result = self.llm._generate([prompt], pipeline_kwargs={"return_full_text": False})
        text = result.generations[0][0].text.strip()
        calls = parse(self.family, text) if tools else []
        # 9 letters or digits: the id shape Mistral templates require
        calls = [{**call, "id": uuid.uuid4().hex[:9], "type": "tool_call"} for call in calls]
        message = AIMessage(content="" if calls else text, tool_calls=calls)
        return ChatResult(generations=[ChatGeneration(message=message)])

    def _dicts(self, messages: list[BaseMessage]) -> list[dict]:
        """Messages in the form chat templates expect, with tool calls and tool results."""
        if self.family == "mistral" and len(messages) > 1 and isinstance(messages[0], SystemMessage):
            # Mistral templates drop the system message after a tool round
            first = messages[1].model_copy(update={"content": f"{messages[0].content}\n\n{messages[1].content}"})
            messages = [first, *messages[2:]]
        dicts = []
        for m in messages:
            d = {"role": ROLES[m.type], "content": m.content}
            if isinstance(m, AIMessage) and m.tool_calls:
                d["tool_calls"] = [
                    {"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": c["args"]}}
                    for c in m.tool_calls
                ]
            if isinstance(m, ToolMessage):
                d = {"role": "tool", "name": m.name, "tool_call_id": m.tool_call_id, "content": m.content}
            dicts.append(d)
        return dicts


def build(spec: ModelSpec) -> BaseChatModel:
    params = dict(spec.params)
    family = params.pop("family", None)
    if not params.pop("local", False):
        return Chat(llm=HuggingFaceEndpoint(repo_id=spec.name, task="text-generation", **params))
    if family not in FAMILIES:
        raise ValueError(f"Local Hugging Face models need params.family, one of: {', '.join(sorted(FAMILIES))}")
    return Chat(llm=HuggingFacePipeline.from_model_id(model_id=spec.name, task="text-generation", **params), family=family)
