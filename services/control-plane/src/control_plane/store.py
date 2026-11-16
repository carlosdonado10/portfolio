"""SQLite persistence: lease state, anonymous sessions, visit log."""

import sqlite3
from pathlib import Path
from typing import Any

from control_plane.lease import State

_SCHEMA = """
CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK (id = 1), json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions (
    sid TEXT PRIMARY KEY,
    email TEXT,
    ip TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL DEFAULT (unixepoch('subsec'))
);
CREATE TABLE IF NOT EXISTS visits (sid TEXT NOT NULL, path TEXT NOT NULL, at REAL NOT NULL);
"""


class Store:
    """One connection, used from the event loop thread only (the Engine's lock
    serialises writers); fine at this traffic."""

    def __init__(self, path: Path) -> None:
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(_SCHEMA)

    def close(self) -> None:
        self._db.close()

    def load_state(self) -> State:
        row = self._db.execute("SELECT json FROM state WHERE id = 1").fetchone()
        return State() if row is None else State.from_json(row["json"])

    def save_state(self, state: State) -> None:
        with self._db:
            self._db.execute(
                "INSERT INTO state (id, json) VALUES (1, ?) "
                "ON CONFLICT(id) DO UPDATE SET json = excluded.json",
                (state.to_json(),),
            )

    def ensure_session(self, sid: str, ip: str) -> None:
        with self._db:
            self._db.execute("INSERT OR IGNORE INTO sessions (sid, ip) VALUES (?, ?)", (sid, ip))

    def set_email(self, sid: str, email: str) -> None:
        with self._db:
            self._db.execute(
                "INSERT INTO sessions (sid, email) VALUES (?, ?) "
                "ON CONFLICT(sid) DO UPDATE SET email = excluded.email",
                (sid, email),
            )

    def get_email(self, sid: str) -> str | None:
        row = self._db.execute("SELECT email FROM sessions WHERE sid = ?", (sid,)).fetchone()
        return None if row is None else row["email"]

    def log_visit(self, sid: str, path: str, at: float) -> None:
        with self._db:
            self._db.execute("INSERT INTO visits (sid, path, at) VALUES (?, ?, ?)", (sid, path, at))

    def list_sessions(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for row in self._db.execute("SELECT sid, email, ip, created_at FROM sessions"):
            visits = self._db.execute(
                "SELECT path, at FROM visits WHERE sid = ? ORDER BY at", (row["sid"],)
            ).fetchall()
            out.append({**dict(row), "visits": [dict(v) for v in visits]})
        return out
