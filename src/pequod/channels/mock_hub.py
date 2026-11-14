"""SQLite store all mocks read/write."""

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from pequod.types import Interaction, Reply

TABLE = """CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY, direction TEXT, channel TEXT, at TEXT, body TEXT, subject TEXT, payload TEXT)"""


def utc(at: datetime) -> str:
    """Stored as UTC text of fixed length, so times compare correctly as strings."""
    if at.tzinfo is None:
        raise ValueError(f"Time without a timezone: {at}")
    return at.astimezone(timezone.utc).isoformat(timespec="microseconds")


class MockHub:
    """Messages sent by the engine ("out") and replies written by whoever plays the client ("in")."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._run(TABLE)

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
