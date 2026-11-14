from conftest import ANGLE, NOW, READ, call, fake, path, wave

from pequod.agents.planner import Planner
from pequod.types import Path

PATHS = [Path(**path()), Path(**path(subgoal="Ask about stock data"))]


def run(graph, catalog, rules, *messages, max_waves=3):
    model = fake(*messages)
    planner = Planner(model, graph, catalog, rules, max_steps=4, max_waves=max_waves, angle=ANGLE)
    return model, planner.run(PATHS, NOW)


def planned(*waves_per_path):
    return call("Paths", paths=[path(*waves) for waves in waves_per_path])


def test_returns_paths_with_waves(graph, catalog, rules):
    _, paths = run(graph, catalog, rules, planned([wave("email")], [wave("sms")]))
    assert [p.waves[0].channel for p in paths] == ["email", "sms"]


def test_keeps_the_strategist_subgoals(graph, catalog, rules):
    answer = call("Paths", paths=[path(wave(), subgoal="changed"), path(wave("sms"), subgoal="changed")])
    _, paths = run(graph, catalog, rules, answer)
    assert [p.subgoals for p in paths] == [p.subgoals for p in PATHS]


def test_tools(graph, catalog, rules):
    model, _ = run(graph, catalog, rules, planned([wave()], [wave("sms")]))
    assert set(model.bound) == READ | {"list_strategies", "channel_rules", "Paths"}


def test_message_has_paths_limit_and_now(graph, catalog, rules):
    model, _ = run(graph, catalog, rules, planned([wave()], [wave("sms")]))
    message = model.seen[0][1].content
    assert "Ask about stock data" in message and "at most 3 waves" in message and NOW.isoformat() in message


def test_extra_waves_are_cut(graph, catalog, rules):
    four = [wave(hour=h) for h in (9, 10, 11, 12)]
    _, paths = run(graph, catalog, rules, planned(four, [wave("sms")]), max_waves=3)
    assert len(paths[0].waves) == 3


def test_path_without_waves_is_rejected_then_fixed(graph, catalog, rules):
    model, paths = run(graph, catalog, rules, planned([], [wave("sms")]), planned([wave()], [wave("sms")]))
    assert all(p.waves for p in paths)
    assert model.seen[1][-1].content.startswith("Error")


def test_wrong_number_of_paths_is_rejected_then_fixed(graph, catalog, rules):
    _, paths = run(graph, catalog, rules, planned([wave()]), planned([wave()], [wave("sms")]))
    assert len(paths) == 2


def test_prompt_ends_with_angle(graph, catalog, rules):
    model, _ = run(graph, catalog, rules, planned([wave()], [wave("sms")]))
    assert model.seen[0][0].content.endswith(ANGLE)
