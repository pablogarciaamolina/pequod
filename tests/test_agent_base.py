import pytest
from conftest import call, fake
from langchain_core.messages import AIMessage
from langchain_core.tools import tool

from pequod.agents.base import Agent, AgentError, checked
from pequod.types import Interaction, StopSignal

PROMPT = "You are a test agent."
AWARE = "2026-11-16T10:00:00+01:00"
STOP = call("StopSignal", opt_out=True, evidence="stop")


@pytest.fixture
def pings():
    return []


def agent(model, pings, **kwargs):
    @tool
    def ping() -> str:
        """Ping."""
        pings.append(1)
        return "pong"

    defaults = dict(name="tester", model=model, system_prompt=PROMPT, tools=[ping], output_type=StopSignal, max_steps=4)
    return Agent(**{**defaults, **kwargs})


def test_invoke_returns_the_output_type(pings):
    out = agent(fake(STOP), pings).invoke("go")
    assert isinstance(out, StopSignal) and out.opt_out is True


def test_agent_can_call_tools_before_answering(pings):
    out = agent(fake(call("ping"), STOP), pings).invoke("go")
    assert out.evidence == "stop" and pings == [1]


def test_model_sees_prompt_tools_and_message(pings):
    model = fake(STOP)
    agent(model, pings).invoke("go now")
    system, user = model.seen[0][0], model.seen[0][1]
    assert system.content == PROMPT
    assert user.content == "go now"
    assert set(model.bound) == {"ping", "StopSignal"}


def test_angle_is_appended_to_the_prompt(pings):
    model = fake(STOP)
    agent(model, pings, angle="Lean on clarity").invoke("go")
    assert model.seen[0][0].content == PROMPT + "\n\nConversational angle: Lean on clarity"


def test_role_is_appended_before_the_angle(pings):
    model = fake(STOP)
    agent(model, pings, angle="Lean on clarity", role="On email: Sam from a pet shop").invoke("go")
    system = model.seen[0][0].content
    assert system.startswith(PROMPT) and system.endswith("Conversational angle: Lean on clarity")
    assert "On email: Sam from a pet shop" in system[len(PROMPT):]


def test_invalid_output_is_returned_to_the_model_then_fixed(pings):
    model = fake(
        call("Interaction", channel="sms", send_at="2026-11-16T10:00:00", body="hi"),
        call("Interaction", channel="sms", send_at=AWARE, body="hi"),
    )
    out = agent(model, pings, output_type=Interaction).invoke("go")
    assert out.send_at.utcoffset() is not None
    assert model.seen[1][-1].content.startswith("Error")


def test_plain_text_answer_gets_a_reminder_then_the_tool_call_is_accepted(pings):
    model = fake(AIMessage(content="The client opted out."), STOP)
    out = agent(model, pings).invoke("go")
    assert out.opt_out is True
    reminder = model.seen[1][-1]
    assert reminder.type == "human" and "StopSignal" in reminder.content
    assert model.seen[1][-2].content == "The client opted out."  # the model still sees its own text


def test_only_plain_text_raises_agent_error_at_the_limit(pings):
    model = fake(*[AIMessage(content="just text") for _ in range(5)])  # separate objects: separate message ids
    with pytest.raises(AgentError, match="tester: no valid StopSignal after 3 model calls.*limit 3.*just text"):
        agent(model, pings, max_steps=3).invoke("go")
    assert len(model.seen) == 3  # the reminder does not buy extra model calls


def test_reminder_and_tool_calls_share_the_step_limit(pings):
    model = fake(call("ping"), AIMessage(content="text"), call("ping"), STOP)
    with pytest.raises(AgentError, match="after 3 model calls"):
        agent(model, pings, max_steps=3).invoke("go")
    assert len(model.seen) == 3


def test_step_limit_raises_agent_error(pings):
    model = fake(*[call("ping") for _ in range(5)])
    with pytest.raises(AgentError, match="after 2 model calls.*limit"):
        agent(model, pings, max_steps=2).invoke("go")
    assert len(pings) == 2


def no_sms(interaction):
    if interaction.channel == "sms":
        raise ValueError("sms is not allowed")


def test_check_rejects_an_output_then_accepts_the_fix(pings):
    model = fake(
        call("Interaction", channel="sms", send_at=AWARE, body="hi"),
        call("Interaction", channel="email", send_at=AWARE, body="hi"),
    )
    out = agent(model, pings, output_type=Interaction).invoke("go", check=no_sms)
    assert type(out) is Interaction and out.channel == "email"
    assert "sms is not allowed" in model.seen[1][-1].content


def test_checked_type_keeps_name_and_description():
    assert checked(Interaction, no_sms).__name__ == "Interaction"
    assert checked(Interaction, no_sms).__doc__ == Interaction.__doc__


def test_provider_error_becomes_an_agent_error_naming_the_agent(pings):
    class Broken(type(fake())):
        def _generate(self, *args, **kwargs):
            raise ConnectionError("no route to host")

    with pytest.raises(AgentError, match="tester: ConnectionError: no route to host"):
        agent(Broken(messages=iter([])), pings).invoke("go")
