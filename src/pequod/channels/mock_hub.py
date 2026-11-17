"""SQLite store all mocks read/write."""

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from pequod.types import Interaction, Message, Reply

TABLES = (
    """CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY, direction TEXT, channel TEXT, at TEXT, body TEXT, subject TEXT, payload TEXT)""",
    "CREATE TABLE IF NOT EXISTS commands (id INTEGER PRIMARY KEY, command TEXT)",  # simulator buttons
    "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)",  # the current run's folder
)
COMMANDS = ("send", "ok", "stop")


def utc(at: datetime) -> str:
    """Stored as UTC text of fixed length, so times compare correctly as strings."""
    if at.tzinfo is None:
        raise ValueError(f"Time without a timezone: {at}")
    return at.astimezone(timezone.utc).isoformat(timespec="microseconds")


class MockHub:
    """Messages sent by the engine ("out") and replies written by whoever plays the persona ("in")."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for table in TABLES:
            self._run(table)

    def _run(self, sql: str, args: tuple = ()) -> tuple[list[tuple], int | None]:
        """Rows and the id of the inserted row. One connection per call: `pequod reply` is another process."""
        with closing(sqlite3.connect(self.path)) as db, db:
            cursor = db.execute(sql, args)
            return cursor.fetchall(), cursor.lastrowid

    def _add(self, direction: str, channel: str, at: datetime, body: str, subject=None, payload=None) -> str:
        sql = "INSERT INTO messages (direction, channel, at, body, subject, payload) VALUES (?, ?, ?, ?, ?, ?)"
        _, rowid = self._run(sql, (direction, channel, utc(at), body, subject, json.dumps(payload)))
        return f"{channel}-{rowid}"

    def add_sent(self, interaction: Interaction, at: datetime) -> str:
        i = interaction
        return self._add("out", i.channel, at, i.body, i.subject, i.payload)

    def add_reply(self, channel: str, body: str, at: datetime) -> str:
        return self._add("in", channel, at, body)

    def replies(self, channel: str, since: datetime) -> list[Reply]:
        sql = "SELECT id, at, body FROM messages WHERE direction = 'in' AND channel = ? AND at >= ? ORDER BY id"
        rows, _ = self._run(sql, (channel, utc(since)))
        return [Reply(id=f"{channel}-{i}", channel=channel, body=body, received_at=at) for i, at, body in rows]

    def sent(self, channel: str | None = None) -> list[dict]:
        sql = "SELECT channel, at, body, subject, payload FROM messages WHERE direction = 'out' ORDER BY id"
        return [
            {"channel": c, "at": datetime.fromisoformat(at), "body": body, "subject": subject, "payload": json.loads(payload)}
            for c, at, body, subject, payload in self._run(sql)[0]
            if channel in (None, c)
        ]

    def conversation(self, channel: str) -> list[Message]:
        """Everything said on one channel, both directions, oldest first."""
        sql = "SELECT direction, at, body, subject, payload FROM messages WHERE channel = ? ORDER BY id"
        return [
            Message(direction=d, channel=channel, at=at, body=body, subject=subject, payload=json.loads(payload))
            for d, at, body, subject, payload in self._run(sql, (channel,))[0]
        ]

    # --- used by the simulator ---

    def start_run(self, folder: str | Path) -> None:
        """A new run: forget the last run's messages and commands, remember where this run writes."""
        with closing(sqlite3.connect(self.path)) as db, db:  # one step for a reader
            db.execute("DELETE FROM messages")
            db.execute("DELETE FROM commands")
            db.execute("DELETE FROM meta")
            db.execute("INSERT INTO meta (key, value) VALUES ('run_folder', ?)", (str(folder),))

    def run_folder(self) -> Path | None:
        rows, _ = self._run("SELECT value FROM meta WHERE key = 'run_folder'")
        return Path(rows[0][0]) if rows else None

    def set_channels(self, persona: dict[str, dict], system: dict[str, dict]) -> None:
        """The two sides of the current run, for the simulator and `pequod reply`:
        `persona` = persona channel name -> {platform, address}; `system` = system channel name ->
        {platform, target}. Messages are keyed by the system channel (the thread)."""
        value = json.dumps({"persona": persona, "system": system})
        self._run("INSERT OR REPLACE INTO meta (key, value) VALUES ('channels', ?)", (value,))

    def channels(self) -> dict[str, dict] | None:
        """{'persona': {name: {platform, address}}, 'system': {name: {platform, target}}}, or None."""
        rows, _ = self._run("SELECT value FROM meta WHERE key = 'channels'")
        return json.loads(rows[0][0]) if rows else None

    def add_command(self, command: str) -> None:
        if command not in COMMANDS:
            raise ValueError(f"Unknown command '{command}'. Use one of: {', '.join(COMMANDS)}")
        self._run("INSERT INTO commands (command) VALUES (?)", (command,))

    def take_commands(self) -> list[str]:
        """Commands not taken yet, oldest first. Each one is returned once."""
        rows, _ = self._run("DELETE FROM commands RETURNING id, command")  # one statement: no caller sees a taken row
        return [command for _, command in sorted(rows)]
