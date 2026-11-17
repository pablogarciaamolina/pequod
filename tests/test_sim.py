import sys

import pytest
from conftest import NOW, interaction, path, wave
from fastapi.testclient import TestClient

from pequod.channels.mock_hub import MockHub
from pequod.trace import Trace
from pequod.types import Interaction, Path, Reply, Resolution, StopSignal
from pequod_sim import app as sim

# The create_app fallback until a run tells the hub its own channels: two persona accounts, each
# reached by one system channel (thread). An email account `work_email` and a whatsapp `phone`.
PERSONA = {"work_email": {"platform": "email", "address": "julius@x.test"},
           "phone": {"platform": "whatsapp", "address": "+49"}}
SYSTEM = {"pepe": {"platform": "email", "target": "work_email"},
          "melina": {"platform": "whatsapp", "target": "phone"}}
CHANNELS = {"persona": PERSONA, "system": SYSTEM}


@pytest.fixture
def hub(tmp_path):
    return MockHub(tmp_path / "hub.db")


@pytest.fixture
def client(hub):
    return TestClient(sim.create_app(hub, CHANNELS, refresh_s=1))


def state(client):
    response = client.get("/api/state")
    assert response.status_code == 200
    return response.json()


def accounts(client):
    return {a["name"]: a for a in state(client)["accounts"]}


def test_page_is_served(client):
    response = client.get("/")
    assert response.status_code == 200 and "text/html" in response.headers["content-type"]
    assert all(label in response.text for label in ("Send now", "Next iteration", "Stop"))


def test_state_before_any_run(client):
    s = state(client)
    assert s["run"] is None and s["refresh_s"] == 1
    acc = {a["name"]: a for a in s["accounts"]}
    assert acc["work_email"]["address"] == "julius@x.test" and acc["work_email"]["platform"] == "email"
    assert [t["name"] for t in acc["work_email"]["threads"]] == ["pepe"]
    assert [t["name"] for t in acc["phone"]["threads"]] == ["melina"]
    assert acc["work_email"]["threads"][0]["messages"] == []


def test_state_shows_messages_waves_status_and_report(client, hub, tmp_path):
    hub.start_run(tmp_path / "run")
    sent = Interaction(**interaction("pepe"), subject="Reports")
    hub.add_sent(sent, NOW)
    hub.add_reply("pepe", "Grüße 👍", NOW)
    trace = Trace(tmp_path / "run")
    trace.record(1, [Path(**path(wave("pepe")))], [sent], [Reply(id="pepe-2", channel="pepe", body="Grüße 👍", received_at=NOW)],
                 StopSignal(opt_out=True, evidence="stop"), "opt_out")
    trace.status("finished", 1, 5)
    trace.report("opt_out", Resolution(report="THE REPORT"))

    s = state(client)
    work = next(a for a in s["accounts"] if a["name"] == "work_email")
    messages = work["threads"][0]["messages"]
    assert [(m["direction"], m["body"], m["subject"]) for m in messages] == [
        ("out", sent.body, "Reports"), ("in", "Grüße 👍", None),
    ]
    run = s["run"]
    assert run["folder"] == str(tmp_path / "run")
    assert (run["status"]["phase"], run["status"]["wave"], run["status"]["max_iterations"]) == ("finished", 1, 5)
    assert len(run["waves"]) == 1 and run["waves"][0]["reason"] == "opt_out"
    assert run["waves"][0]["stop_signal"]["opt_out"] is True and run["waves"][0]["snapshot"] == "graph_0.json"
    assert "THE REPORT" in run["report"]


def test_state_of_a_run_that_has_just_started(client, hub, tmp_path):
    hub.start_run(tmp_path / "run")
    Trace(tmp_path / "run").status("planning", 1, 5)
    run = state(client)["run"]
    assert run["status"]["phase"] == "planning" and run["waves"] == [] and run["report"] is None


def test_state_survives_a_missing_run_folder(client, hub, tmp_path):
    hub.start_run(tmp_path / "gone")
    run = state(client)["run"]
    assert run == {"folder": str(tmp_path / "gone"), "status": None, "waves": [], "report": None}
    assert not (tmp_path / "gone").exists()  # looking must not create it


def test_reply_is_stored(client, hub):
    response = client.post("/api/reply", json={"channel": "melina", "text": "Our stock numbers are a day old"})
    assert response.status_code == 200
    (reply,) = hub.conversation("melina")
    assert (reply.direction, reply.body) == ("in", "Our stock numbers are a day old")


@pytest.mark.parametrize("body", [{"channel": "fax", "text": "x"}, {"channel": "pepe", "text": ""},
                                  {"channel": "pepe", "text": "   "}, {"channel": "pepe"}, {}])
def test_reply_errors(client, hub, body):
    assert client.post("/api/reply", json=body).status_code == 422
    assert all(hub.conversation(c) == [] for c in SYSTEM)


@pytest.mark.parametrize("command", ["send", "ok", "stop"])
def test_command_is_stored(client, hub, command):
    assert client.post("/api/command", json={"command": command}).status_code == 200
    assert hub.take_commands() == [command]


@pytest.mark.parametrize("body", [{"command": "explode"}, {"command": ""}, {}])
def test_unknown_command_is_rejected(client, hub, body):
    assert client.post("/api/command", json=body).status_code == 422
    assert hub.take_commands() == []


def test_text_is_returned_as_data_not_as_html(client, hub):
    hub.add_reply("pepe", "<script>alert(1)</script>", NOW)
    response = client.get("/api/state")
    assert response.headers["content-type"].startswith("application/json")
    work = next(a for a in response.json()["accounts"] if a["name"] == "work_email")
    assert work["threads"][0]["messages"][0]["body"] == "<script>alert(1)</script>"


def test_main_starts_the_server_from_the_configs(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["pequod-sim"])
    seen = {}
    monkeypatch.setattr(sim.uvicorn, "run", lambda app, **kwargs: seen.update(app=app, **kwargs))
    sim.main()
    assert (seen["host"], seen["port"]) == ("127.0.0.1", 8000)
    s = TestClient(seen["app"]).get("/api/state").json()
    assert [a["name"] for a in s["accounts"]] == ["work_email", "company_sms", "personal_whatsapp"] and s["refresh_s"] == 1
    assert (tmp_path / "runs" / "mock_hub.db").exists()  # the same hub file as the engine and `pequod reply`


def test_sim_command_is_installed():
    from importlib.metadata import entry_points

    (script,) = entry_points(group="console_scripts", name="pequod-sim")
    assert script.value == "pequod_sim.app:main"


def test_page_shows_the_channels_of_the_running_run(client, hub, tmp_path):
    """The engine may run another engagement than the default one."""
    hub.start_run(tmp_path / "run")
    hub.set_channels({"inbox": {"platform": "email", "address": "someone@customer.test"}},
                     {"sender": {"platform": "email", "target": "inbox"}})
    acc = accounts(client)
    assert list(acc) == ["inbox"] and [t["name"] for t in acc["inbox"]["threads"]] == ["sender"]
    assert client.post("/api/reply", json={"channel": "melina", "text": "hi"}).status_code == 422
    assert client.post("/api/reply", json={"channel": "sender", "text": "hi"}).status_code == 200


def test_several_threads_nest_under_one_account(client, hub, tmp_path):
    hub.start_run(tmp_path / "run")
    hub.set_channels({"work_email": {"platform": "email", "address": "j@x.test"}},
                     {"pepe": {"platform": "email", "target": "work_email"},
                      "boss": {"platform": "email", "target": "work_email"}})
    hub.add_sent(Interaction(**interaction("pepe", "from pepe")), NOW)
    (work,) = state(client)["accounts"]
    threads = {t["name"]: t for t in work["threads"]}
    assert set(threads) == {"pepe", "boss"}
    assert [m["body"] for m in threads["pepe"]["messages"]] == ["from pepe"]
    assert threads["boss"]["messages"] == []


def test_reply_goes_to_the_named_thread_only(client, hub, tmp_path):
    hub.start_run(tmp_path / "run")
    hub.set_channels({"work_email": {"platform": "email", "address": "j@x.test"}},
                     {"pepe": {"platform": "email", "target": "work_email"},
                      "boss": {"platform": "email", "target": "work_email"}})
    assert client.post("/api/reply", json={"channel": "boss", "text": "hi boss"}).status_code == 200
    assert [m.body for m in hub.conversation("boss")] == ["hi boss"]
    assert hub.conversation("pepe") == []
