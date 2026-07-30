from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


class HistoryStore:
    """负责把前端用户状态落到本地 SQLite，提供轻量级历史恢复能力。"""

    def __init__(self, db_path: Path | None = None) -> None:
        # 默认数据库放在 backend/data 下，便于随项目运行环境一起管理。
        self.db_path = db_path or Path(__file__).resolve().parents[1] / "data" / "history.sqlite3"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        """创建数据库连接，并让查询结果可以按字段名读取。"""
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self) -> None:
        """初始化历史相关表；重复启动服务时不会覆盖已有数据。"""
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
        """读取指定用户最近一次保存的完整页面状态。"""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT state_json, updated_at FROM user_states WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        if not row:
            return None
        try:
            # state_json 由前端统一打包，后端只负责保存和恢复，不拆散业务字段。
            state = json.loads(row["state_json"])
        except json.JSONDecodeError:
            return None
        if isinstance(state, dict):
            # 附带服务端更新时间，前端需要时可以用来判断恢复来源。
            state["_server_updated_at"] = row["updated_at"]
            return state
        return None

    def save_state(
        self,
        user_id: str,
        state: dict[str, Any],
        username: str | None = None,
    ) -> dict[str, Any]:
        """保存用户当前状态；同一用户再次保存时更新原有记录。"""
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
        """记录一次历史操作事件，便于后续查看保存行为或扩展审计信息。"""
        payload_json = json.dumps(payload, ensure_ascii=False)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO history_events (user_id, event_type, payload_json)
                VALUES (?, ?, ?)
                """,
                (user_id, event_type, payload_json),
            )


# 对外暴露单例，API 层直接复用同一个历史存储入口。
history_store = HistoryStore()
