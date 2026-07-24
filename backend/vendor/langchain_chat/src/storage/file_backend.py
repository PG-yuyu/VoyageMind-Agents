"""File 存储后端实现。

实现 StorageBackend 定义的全部接口方法，用 JSON 文件存取数据。
对应需求文档第四章「存储架构」（File 为零依赖后端）。

设计说明：
    - 每种实体（users/sessions/messages/presets/user_configs）存为一个 JSON 文件。
    - 每个文件是 JSON 数组，每个元素是一条记录。
    - datetime 字段以 ISO 格式字符串存储。
    - 级联删除手动实现（没有数据库的 ON DELETE CASCADE）。
    - 性能：每次操作读写整个文件，适合小数据量。
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from models.schemas import Message, Preset, Session, User, UserConfig
from storage.base import StorageBackend


class FileBackend(StorageBackend):
    """File 存储后端（JSON 文件存取）。

    使用前必须先调用 initialize()。
    """

    def __init__(self, base_path: str = "data/filestore"):
        self.base_path = Path(base_path)
        self._users_file = None
        self._sessions_file = None
        self._messages_file = None
        self._presets_file = None
        self._configs_file = None

    # ── 初始化与清理 ──────────────────────────────────────────────────────

    async def initialize(self) -> None:
        """初始化：创建目录和空 JSON 文件。"""
        self.base_path.mkdir(parents=True, exist_ok=True)
        self._users_file = self.base_path / "users.json"
        self._sessions_file = self.base_path / "sessions.json"
        self._messages_file = self.base_path / "messages.json"
        self._presets_file = self.base_path / "presets.json"
        self._configs_file = self.base_path / "user_configs.json"
        for f in [self._users_file, self._sessions_file, self._messages_file,
                  self._presets_file, self._configs_file]:
            if not f.exists():
                self._write_json(f, [])

    async def close(self) -> None:
        """关闭（File 后端无需关闭）。"""
        pass

    # ── 辅助方法 ──────────────────────────────────────────────────────────

    def _read_json(self, filepath: Path) -> list:
        if not filepath.exists():
            return []
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []

    def _write_json(self, filepath: Path, data: list) -> None:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    @staticmethod
    def _next_id(records: list) -> int:
        if not records:
            return 1
        return max(r["id"] for r in records) + 1

    @staticmethod
    def _dt_to_str(dt: datetime) -> str:
        return dt.isoformat()

    @staticmethod
    def _str_to_dt(s: str) -> datetime:
        return datetime.fromisoformat(s)

    # ── 用户相关 ──────────────────────────────────────────────────────────

    async def create_user(self, user: User) -> User:
        records = self._read_json(self._users_file)
        user.id = self._next_id(records)
        records.append({
            "id": user.id, "username": user.username,
            "default_model": user.default_model, "default_preset_id": user.default_preset_id,
            "created_at": self._dt_to_str(user.created_at), "updated_at": self._dt_to_str(user.updated_at),
        })
        self._write_json(self._users_file, records)
        return user

    async def get_user_by_name(self, username: str) -> Optional[User]:
        records = self._read_json(self._users_file)
        for r in records:
            if r["username"] == username:
                return self._row_to_user(r)
        return None

    async def list_users(self) -> list[User]:
        records = self._read_json(self._users_file)
        return [self._row_to_user(r) for r in sorted(records, key=lambda x: x["id"])]

    async def delete_user(self, user_id: int) -> None:
        records = self._read_json(self._users_file)
        records = [r for r in records if r["id"] != user_id]
        self._write_json(self._users_file, records)
        await self._cascade_delete_user(user_id)

    async def update_user(self, user: User) -> None:
        records = self._read_json(self._users_file)
        for r in records:
            if r["id"] == user.id:
                r["username"] = user.username
                r["default_model"] = user.default_model
                r["default_preset_id"] = user.default_preset_id
                r["updated_at"] = self._dt_to_str(user.updated_at)
                break
        self._write_json(self._users_file, records)

    async def _cascade_delete_user(self, user_id: int) -> None:
        sessions = self._read_json(self._sessions_file)
        session_ids = {s["id"] for s in sessions if s["user_id"] == user_id}
        sessions = [s for s in sessions if s["user_id"] != user_id]
        self._write_json(self._sessions_file, sessions)
        messages = self._read_json(self._messages_file)
        messages = [m for m in messages if m["session_id"] not in session_ids]
        self._write_json(self._messages_file, messages)
        presets = self._read_json(self._presets_file)
        presets = [p for p in presets if p.get("user_id") != user_id]
        self._write_json(self._presets_file, presets)
        configs = self._read_json(self._configs_file)
        configs = [c for c in configs if c["user_id"] != user_id]
        self._write_json(self._configs_file, configs)

    @staticmethod
    def _row_to_user(r: dict) -> User:
        return User(
            id=r["id"], username=r["username"],
            default_model=r.get("default_model"), default_preset_id=r.get("default_preset_id"),
            created_at=FileBackend._str_to_dt(r["created_at"]),
            updated_at=FileBackend._str_to_dt(r["updated_at"]),
        )

    # ── 会话相关 ──────────────────────────────────────────────────────────

    async def create_session(self, session: Session) -> Session:
        records = self._read_json(self._sessions_file)
        session.id = self._next_id(records)
        records.append({
            "id": session.id, "user_id": session.user_id, "title": session.title,
            "model_name": session.model_name, "preset_id": session.preset_id,
            "total_prompt_tokens": session.total_prompt_tokens,
            "total_completion_tokens": session.total_completion_tokens,
            "created_at": self._dt_to_str(session.created_at), "updated_at": self._dt_to_str(session.updated_at),
        })
        self._write_json(self._sessions_file, records)
        return session

    async def get_session(self, session_id: int) -> Optional[Session]:
        records = self._read_json(self._sessions_file)
        for r in records:
            if r["id"] == session_id:
                return self._row_to_session(r)
        return None

    async def list_sessions(self, user_id: int, limit: int = 0, offset: int = 0) -> list[Session]:
        records = self._read_json(self._sessions_file)
        filtered = [r for r in records if r["user_id"] == user_id]
        result = [self._row_to_session(r) for r in sorted(filtered, key=lambda x: x["id"], reverse=True)]
        if limit > 0:
            return result[offset:offset + limit]
        return result

    async def update_session(self, session: Session) -> None:
        session.updated_at = datetime.now(timezone.utc)
        records = self._read_json(self._sessions_file)
        for r in records:
            if r["id"] == session.id:
                r["title"] = session.title
                r["model_name"] = session.model_name
                r["preset_id"] = session.preset_id
                r["total_prompt_tokens"] = session.total_prompt_tokens
                r["total_completion_tokens"] = session.total_completion_tokens
                r["updated_at"] = self._dt_to_str(session.updated_at)
                break
        self._write_json(self._sessions_file, records)

    async def delete_session(self, session_id: int) -> None:
        records = self._read_json(self._sessions_file)
        records = [r for r in records if r["id"] != session_id]
        self._write_json(self._sessions_file, records)
        messages = self._read_json(self._messages_file)
        messages = [m for m in messages if m["session_id"] != session_id]
        self._write_json(self._messages_file, messages)

    async def delete_sessions_by_user(self, user_id: int) -> None:
        # 先找出该用户的全部会话 id，再删会话和对应消息（无 CASCADE，手动清理）
        records = self._read_json(self._sessions_file)
        user_session_ids = {r["id"] for r in records if r["user_id"] == user_id}
        records = [r for r in records if r["user_id"] != user_id]
        self._write_json(self._sessions_file, records)
        messages = self._read_json(self._messages_file)
        messages = [m for m in messages if m["session_id"] not in user_session_ids]
        self._write_json(self._messages_file, messages)

    @staticmethod
    def _row_to_session(r: dict) -> Session:
        return Session(
            id=r["id"], user_id=r["user_id"], title=r["title"],
            model_name=r["model_name"], preset_id=r.get("preset_id"),
            total_prompt_tokens=r.get("total_prompt_tokens", 0),
            total_completion_tokens=r.get("total_completion_tokens", 0),
            created_at=FileBackend._str_to_dt(r["created_at"]),
            updated_at=FileBackend._str_to_dt(r["updated_at"]),
        )

    # ── 消息相关 ──────────────────────────────────────────────────────────

    async def add_message(self, message: Message) -> Message:
        records = self._read_json(self._messages_file)
        message.id = self._next_id(records)
        records.append({
            "id": message.id, "session_id": message.session_id, "role": message.role,
            "content": message.content, "prompt_tokens": message.prompt_tokens,
            "completion_tokens": message.completion_tokens,
            "created_at": self._dt_to_str(message.created_at),
        })
        self._write_json(self._messages_file, records)
        return message

    async def list_messages(self, session_id: int) -> list[Message]:
        records = self._read_json(self._messages_file)
        filtered = [r for r in records if r["session_id"] == session_id]
        return [self._row_to_message(r) for r in sorted(filtered, key=lambda x: x["id"])]

    async def search_messages(self, user_id: int, keyword: str) -> list[Message]:
        sessions = self._read_json(self._sessions_file)
        session_ids = {s["id"] for s in sessions if s["user_id"] == user_id}
        records = self._read_json(self._messages_file)
        result = []
        for r in records:
            if r["session_id"] in session_ids and keyword.lower() in r["content"].lower():
                result.append(r)
        return [self._row_to_message(r) for r in sorted(result, key=lambda x: x["id"])]

    @staticmethod
    def _row_to_message(r: dict) -> Message:
        return Message(
            id=r["id"], session_id=r["session_id"], role=r["role"],
            content=r["content"], prompt_tokens=r.get("prompt_tokens", 0),
            completion_tokens=r.get("completion_tokens", 0),
            created_at=FileBackend._str_to_dt(r["created_at"]),
        )

    # ── 预设相关 ──────────────────────────────────────────────────────────

    async def get_preset_by_id(self, preset_id: int) -> Optional[Preset]:
        records = self._read_json(self._presets_file)
        for r in records:
            if r["id"] == preset_id:
                return self._row_to_preset(r)
        return None

    async def save_preset(self, preset: Preset) -> Preset:
        records = self._read_json(self._presets_file)
        if not preset.id:
            preset.id = self._next_id(records)
            records.append({
                "id": preset.id, "user_id": preset.user_id, "name": preset.name,
                "description": preset.description, "system_prompt": preset.system_prompt,
                "is_builtin": preset.is_builtin,
                "created_at": self._dt_to_str(preset.created_at), "updated_at": self._dt_to_str(preset.updated_at),
            })
        else:
            for r in records:
                if r["id"] == preset.id:
                    r["name"] = preset.name
                    r["description"] = preset.description
                    r["system_prompt"] = preset.system_prompt
                    r["is_builtin"] = preset.is_builtin
                    r["updated_at"] = self._dt_to_str(preset.updated_at)
                    break
        self._write_json(self._presets_file, records)
        return preset

    async def list_presets(self, user_id: int) -> list[Preset]:
        records = self._read_json(self._presets_file)
        filtered = [r for r in records if r.get("user_id") is None or r.get("user_id") == user_id]
        return [self._row_to_preset(r) for r in sorted(filtered, key=lambda x: x["id"])]

    async def delete_preset(self, preset_id: int) -> None:
        records = self._read_json(self._presets_file)
        records = [r for r in records if r["id"] != preset_id]
        self._write_json(self._presets_file, records)

    @staticmethod
    def _row_to_preset(r: dict) -> Preset:
        return Preset(
            id=r["id"], user_id=r.get("user_id"), name=r["name"],
            description=r.get("description", ""), system_prompt=r["system_prompt"],
            is_builtin=r.get("is_builtin", False),
            created_at=FileBackend._str_to_dt(r["created_at"]),
            updated_at=FileBackend._str_to_dt(r["updated_at"]),
        )

    # ── 用户配置相关 ──────────────────────────────────────────────────────

    async def get_user_config(self, user_id: int, key: str) -> Optional[str]:
        records = self._read_json(self._configs_file)
        for r in records:
            if r["user_id"] == user_id and r["key"] == key:
                return r["value"]
        return None

    async def set_user_config(self, config: UserConfig) -> None:
        records = self._read_json(self._configs_file)
        for r in records:
            if r["user_id"] == config.user_id and r["key"] == config.key:
                r["value"] = config.value
                r["updated_at"] = self._dt_to_str(config.updated_at)
                self._write_json(self._configs_file, records)
                return
        config.id = self._next_id(records)
        records.append({
            "id": config.id, "user_id": config.user_id, "key": config.key,
            "value": config.value, "updated_at": self._dt_to_str(config.updated_at),
        })
        self._write_json(self._configs_file, records)
