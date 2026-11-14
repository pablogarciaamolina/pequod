"""Agent: model + prompt + tools + output type + max_steps."""

import json
from collections.abc import Callable

from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware
from langchain.agents.structured_output import ToolStrategy
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from pydantic import BaseModel, create_model, model_validator

from pequod.types import ChannelRules, Interaction


def checked(base: type[BaseModel], check: Callable[[BaseModel], None]) -> type[BaseModel]:
    """Same type (name, fields, description) that also runs `check`; `check` raises ValueError to reject."""

    def _run(self):
        check(self)
        return self

    return create_model(
        base.__name__,
        __base__=base,
        __doc__=base.__doc__,
        __validators__={"check": model_validator(mode="after")(_run)},
    )


def dump(items: list[BaseModel]) -> str:
    """Pydantic objects as a JSON list, for agent messages."""
    return json.dumps([i.model_dump(mode="json") for i in items], indent=2)


def fits(interaction: Interaction, rules: ChannelRules) -> None:
    """Raise ValueError when the message breaks its channel's length or subject rule."""
    i = interaction
    if len(i.body) > rules.max_length:
        raise ValueError(f"The {i.channel} body has {len(i.body)} characters; the maximum is {rules.max_length}.")
    if i.subject and not rules.subject:
        raise ValueError(f"{i.channel} has no subject line; leave subject empty.")


class AgentError(RuntimeError):
    """The agent ended without a valid output."""


class Agent:
    """A small ReAct loop: think, call tools, return `output_type`. One step = one model call."""

    def __init__(
        self,
        name: str,
        model: BaseChatModel,
        system_prompt: str,
        tools: list[BaseTool],
        output_type: type[BaseModel],
        max_steps: int,
        angle: str = "",
    ) -> None:
        self.name = name
        self.model = model
        self.system_prompt = system_prompt + (f"\n\nConversational angle: {angle}" if angle else "")
        self.tools = tools
        self.output_type = output_type
        self.max_steps = max_steps

    def invoke(self, message: str, check: Callable[[BaseModel], None] | None = None) -> BaseModel:
        """Run the loop. `check` rejects an output by raising ValueError; the error goes back to the model."""
        output_type = checked(self.output_type, check) if check else self.output_type
        messages: list = [("user", message)]
        calls = 0
        while True:
            agent = create_agent(
                model=self.model,
                tools=self.tools,
                system_prompt=self.system_prompt,
                response_format=ToolStrategy(output_type),
                middleware=[ModelCallLimitMiddleware(run_limit=self.max_steps - calls)],
            )
            try:
                result = agent.invoke({"messages": messages})
            except Exception as e:  # provider failures (auth, rate limit, network): name the agent
                raise AgentError(f"{self.name}: {type(e).__name__}: {e}") from e
            out = result.get("structured_response")
            messages = result["messages"]
            calls = min(sum(m.type == "ai" for m in messages), self.max_steps)
            if out is not None or calls >= self.max_steps:
                break
            # The model answered in plain text (some providers ignore forced tool choice): remind it.
            messages = [*messages, ("user", f"Give your answer by calling the `{output_type.__name__}` tool.")]
        if out is None:
            last = next(m for m in reversed(messages) if m.type == "ai" and "call limits exceeded" not in str(m.content))
            raise AgentError(
                f"{self.name}: no valid {output_type.__name__} after {calls} model calls "
                f"(limit {self.max_steps}). Last message: {str(last.content)[:300]}"
            )
        return self.output_type.model_validate(out.model_dump()) if check else out
