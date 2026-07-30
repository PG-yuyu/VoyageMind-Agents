from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


class HistoryStore:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or Path(__file__).resolve().parents[1] / "data" / "history.sqlite3"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS user_states (
                    user_id TEXT PRIMARY KEY,
                    username TEXT,
                    state_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS history_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def get_state(self, user_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT state_json, updated_at FROM user_states WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        if not row:
            return None
        try:
            state = json.loads(row["state_json"])
        except json.JSONDecodeError:
            return None
        if isinstance(state, dict):
            state["_server_updated_at"] = row["updated_at"]
            return state
        return None

    def save_state(
        self,
        user_id: str,
        state: dict[str, Any],
        username: str | None = None,
    ) -> dict[str, Any]:
        state_json = json.dumps(state, ensure_ascii=False)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO user_states (user_id, username, state_json, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id) DO UPDATE SET
                    username = excluded.username,
                    state_json = excluded.state_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (user_id, username, state_json),
            )
        return {"user_id": user_id, "saved": True}

    def add_event(self, user_id: str, event_type: str, payload: dict[str, Any]) -> None:
        payload_json = json.dumps(payload, ensure_ascii=False)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO history_events (user_id, event_type, payload_json)
                VALUES (?, ?, ?)
                """,
                (user_id, event_type, payload_json),
            )


history_store = HistoryStore()
