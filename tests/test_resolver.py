import pytest
from conftest import ANGLE, READ, call, fake

from pequod.agents.resolver import Resolver
from pequod.types import Resolution, StopSignal

OBJECTIVE = "Surface the real underlying problem and resolve it."
SIGNAL = StopSignal(root_problem_stated=True, evidence="the sync only runs at night")
REASONS = ["root_problem_stated", "solution_accepted", "opt_out", "max_iterations", "operator_stop"]


def run(graph, reason="root_problem_stated"):
    model = fake(call("Resolution", report="Learned: nightly sync. Recommended reply: enable hourly sync."))
    return model, Resolver(model, graph, max_steps=4, angle=ANGLE).run(reason, SIGNAL, OBJECTIVE)


def test_returns_resolution(graph):
    _, out = run(graph)
    assert type(out) is Resolution and "hourly sync" in out.report


def test_has_only_read_tools(graph):
    model, _ = run(graph)
    assert set(model.bound) == READ | {"Resolution"}


@pytest.mark.parametrize("reason", REASONS)
def test_message_has_reason_evidence_and_objective(graph, reason):
    model, _ = run(graph, reason=reason)
    message = model.seen[0][1].content
    assert reason in message and "the sync only runs at night" in message and OBJECTIVE in message


def test_resolution_is_a_report_only():
    assert set(Resolution.model_fields) == {"report"}


def test_prompt_ends_with_angle(graph):
    model, _ = run(graph)
    assert model.seen[0][0].content.endswith(ANGLE)
