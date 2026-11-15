"""The simulator's server: one page and a small JSON API over the mock hub and the run folder.

It never talks to the engine directly. Replies and button commands are written into the hub;
messages come from the hub; the engine's progress comes from the files of the current run folder.
"""

from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from hydra import compose, initialize_config_dir
from omegaconf import OmegaConf
from pydantic import BaseModel

from pequod.channels.mock_hub import MockHub
from pequod.main import CONFIGS, now
from pequod.trace import Trace

PAGE = Path(__file__).parent / "index.html"


class ReplyIn(BaseModel):
    channel: str
    text: str


class CommandIn(BaseModel):
    command: str


def create_app(hub: MockHub, channels: dict[str, str], refresh_s: float) -> FastAPI:
    """`channels` (name -> the persona's address) is used until a run has told the hub its own channels."""
    app = FastAPI(title="Pequod simulator")

    def current() -> dict[str, str]:
        return hub.channels() or channels

    @app.get("/")
    def page() -> FileResponse:
        return FileResponse(PAGE, headers={"Cache-Control": "no-store"})

    @app.get("/api/state")
    def state() -> dict:
        """Everything the page shows; the page asks for it every `refresh_s` seconds."""
        folder = hub.run_folder()
        run = None
        if folder is not None:
            run = {"folder": str(folder), "status": None, "waves": [], "report": None}
            if folder.is_dir():
                trace = Trace(folder)
                status = trace.read_status()
                run["status"] = status.model_dump(mode="json") if status else None
                run["waves"] = [record.model_dump(mode="json") for record in trace.records()]
                run["report"] = trace.read_report()
        return {
            "refresh_s": refresh_s,
            "channels": [
                {"name": name, "address": address, "messages": [m.model_dump(mode="json") for m in hub.conversation(name)]}
                for name, address in current().items()
            ],
            "run": run,
        }

    @app.post("/api/reply")
    def reply(body: ReplyIn) -> dict:
        """The person playing the persona answers on one channel."""
        if body.channel not in current():
            raise HTTPException(422, f"Unknown channel '{body.channel}'. Use one of: {', '.join(current())}")
        if not body.text.strip():
            raise HTTPException(422, "The reply is empty.")
        hub.add_reply(body.channel, body.text.strip(), now())
        return {"ok": True}

    @app.post("/api/command")
    def command(body: CommandIn) -> dict:
        """A button of the engine panel: send, ok (next iteration) or stop."""
        try:
            hub.add_command(body.command)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        return {"ok": True}

    return app


def main() -> None:
    """Console entry `pequod-sim`. Own settings in configs/sim.yaml; hub path and channels from the engine's config."""
    with initialize_config_dir(config_dir=CONFIGS, version_base=None):
        engine = compose(config_name="config")
    own = OmegaConf.load(Path(CONFIGS) / "sim.yaml")
    channels = {name: channel.address for name, channel in engine.engagement.channels.items()}
    hub = MockHub(engine.mock_hub)
    print(f"Pequod simulator: http://{own.host}:{own.port}  (stop with Ctrl+C)")
    print(f"Hub: {hub.path.resolve()}  (start `pequod` in the same folder)")
    uvicorn.run(create_app(hub, channels, own.refresh_s), host=own.host, port=own.port, log_level="warning")
