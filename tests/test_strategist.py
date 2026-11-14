from conftest import READ, call, fake, path, wave

from pequod.agents import strategist
from pequod.agents.strategist import Strategist
from pequod.types import Path

OBJECTIVE = "Surface the real underlying problem and resolve it."


def run(graph, *messages, max_paths=2):
    model = fake(*messages)
    return model, Strategist(model, graph, max_steps=4, max_paths=max_paths).run(OBJECTIVE)


def test_returns_paths(graph):
    _, paths = run(graph, call("Paths", paths=[path(), path(subgoal="Ask about stock data")]))
    assert len(paths) == 2 and all(isinstance(p, Path) for p in paths)
    assert paths[1].subgoals[0] == "Ask about stock data"


def test_has_only_read_tools(graph):
    model, _ = run(graph, call("Paths", paths=[path()]))
    assert set(model.bound) == READ | {"Paths"}


def test_message_has_objective_and_limit(graph):
    model, _ = run(graph, call("Paths", paths=[path()]), max_paths=2)
    message = model.seen[0][1].content
    assert OBJECTIVE in message and "at most 2 paths" in message


def test_extra_paths_are_cut(graph):
    _, paths = run(graph, call("Paths", paths=[path(subgoal=s) for s in "abc"]), max_paths=2)
    assert [p.subgoals[0] for p in paths] == ["a", "b"]


def test_prompt_has_no_angle(graph):
    model, _ = run(graph, call("Paths", paths=[path()]))
    assert model.seen[0][0].content == strategist.PROMPT


def test_waves_from_the_strategist_are_dropped(graph):
    _, paths = run(graph, call("Paths", paths=[path(wave())]))
    assert paths[0].waves == []
