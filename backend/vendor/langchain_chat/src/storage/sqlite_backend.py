"""SQLite 存储后端实现。

实现 StorageBackend 定义的全部接口方法，用 aiosqlite 异步驱动操作 SQLite。
对应需求文档第四章「存储架构」（SQLite 为默认后端）。

设计说明：
    - 用 aiosqlite 异步访问数据库（项目全链路异步，需求 A3）。
    - datetime 字段统一以 ISO 格式字符串存储（TEXT 类型），读取时转回 datetime。
    - id 字段用 INTEGER PRIMARY KEY AUTOINCREMENT 自增。
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import aiosqlite

from models.schemas import Message, Preset, Session, User, UserConfig
from storage.base import StorageBackend


class SQLiteBackend(StorageBackend):
    """SQLite 存储后端。

    使用前必须先调用 initialize() 建表，使用结束调用 close() 关闭连接。
    """

    def __init__(self, db_path: str = "data/sqlite/app.db"):
        # 数据库文件路径（相对于运行目录）
        self.db_path = db_path
        # 连接对象（initialize 后才有值）
        self._conn: Optional[aiosqlite.Connection] = None

    # ── 初始化与清理 ──────────────────────────────────────────────────────

    async def initialize(self) -> None:
        """初始化：建目录、打开连接、建表。"""
        # 确保数据库所在目录存在（否则 aiosqlite.connect 会失败）
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        # 打开连接（启用外键约束，让 ON DELETE CASCADE 生效）
        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row  # 查询结果按列名访问
        await self._conn.execute("PRAGMA foreign_keys = ON")

        # 建表
        await self._create_tables()
        await self._conn.commit()

    async def close(self) -> None:
        """关闭连接。"""
        if self._conn:
            await self._conn.close()
            self._conn = None

    async def _create_tables(self) -> None:
        """创建所有表（IF NOT EXISTS 保证可重复执行）。"""
        await self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                default_model TEXT,
                default_preset_id INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (default_preset_id) REFERENCES presets(id)
            );

            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                model_name TEXT NOT NULL,
                preset_id INTEGER,
                total_prompt_tokens INTEGER NOT NULL DEFAULT 0,
                total_completion_tokens INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (preset_id) REFERENCES presets(id)
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('human','ai','system')),
                content TEXT NOT NULL,
                prompt_tokens INTEGER NOT NULL DEFAULT 0,
                completion_tokens INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS presets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                system_prompt TEXT NOT NULL,
                is_builtin INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS user_configs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );
        """)

    # ── 辅助方法 ──────────────────────────────────────────────────────────

    @staticmethod
    def _dt_to_str(dt: datetime) -> str:
        """datetime 转 ISO 字符串存储。"""
        return dt.isoformat()

    @staticmethod
    def _str_to_dt(s: str) -> datetime:
        """ISO 字符串转回 datetime。"""
        return datetime.fromisoformat(s)

    # ── 用户相关 ──────────────────────────────────────────────────────────

    async def create_user(self, user: User) -> User:
        """创建用户。返回含分配 id 的 User。"""
        cursor = await self._conn.execute(
            """INSERT INTO users (username, default_model, default_preset_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (user.username, user.default_model, user.default_preset_id,
             self._dt_to_str(user.created_at), self._dt_to_str(user.updated_at)),
        )
        await self._conn.commit()
        user.id = cursor.lastrowid
        return user

    async def get_user_by_name(self, username: str) -> Optional[User]:
        """按用户名查询。不存在返回 None。"""
        async with self._conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ) as cursor:
            row = await cursor.fetchone()
            return self._row_to_user(row) if row else None

    async def list_users(self) -> list[User]:
        """列出所有用户。"""
        async with self._conn.execute("SELECT * FROM users ORDER BY id") as cursor:
            rows = await cursor.fetchall()
            return [self._row_to_user(r) for r in rows]

    async def delete_user(self, user_id: int) -> None:
        """删除用户（关联数据靠 ON DELETE CASCADE 自动清理）。"""
        await self._conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        await self._conn.commit()
    async def update_user(self, user: User) -> None:
        """更新用户信息。"""
        await self._conn.execute(
            """UPDATE users SET username=?, default_model=?, default_preset_id=?,
               updated_at=? WHERE id=?""",
            (user.username, user.default_model, user.default_preset_id,
             self._dt_to_str(user.updated_at), user.id),
        )
        await self._conn.commit()

    @staticmethod
    def _row_to_user(row: aiosqlite.Row) -> User:
        return User(
            id=row["id"], username=row["username"],
            default_model=row["default_model"], default_preset_id=row["default_preset_id"],
            created_at=SQLiteBackend._str_to_dt(row["created_at"]),
            updated_at=SQLiteBackend._str_to_dt(row["updated_at"]),
        )

    # ── 会话相关 ──────────────────────────────────────────────────────────

    async def create_session(self, session: Session) -> Session:
        cursor = await self._conn.execute(
            """INSERT INTO sessions (user_id, title, model_name, preset_id,
               total_prompt_tokens, total_completion_tokens, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (session.user_id, session.title, session.model_name, session.preset_id,
             session.total_prompt_tokens, session.total_completion_tokens,
             self._dt_to_str(session.created_at), self._dt_to_str(session.updated_at)),
        )
        await self._conn.commit()
        session.id = cursor.lastrowid
        return session

    async def get_session(self, session_id: int) -> Optional[Session]:
        async with self._conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return self._row_to_session(row) if row else None

    async def list_sessions(self, user_id: int, limit: int = 0, offset: int = 0) -> list[Session]:
        sql = "SELECT * FROM sessions WHERE user_id = ? ORDER BY id DESC"
        params: list = [user_id]
        if limit > 0:
            sql += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])
        async with self._conn.execute(sql, params) as cursor:
            rows = await cursor.fetchall()
            return [self._row_to_session(r) for r in rows]

    async def update_session(self, session: Session) -> None:
        # 更新 updated_at 为当前时间
        session.updated_at = datetime.now(timezone.utc)
        await self._conn.execute(
            """UPDATE sessions SET title=?, model_name=?, preset_id=?,
               total_prompt_tokens=?, total_completion_tokens=?, updated_at=? WHERE id=?""",
            (session.title, session.model_name, session.preset_id,
             session.total_prompt_tokens, session.total_completion_tokens,
             self._dt_to_str(session.updated_at), session.id),
        )
        await self._conn.commit()

    async def delete_session(self, session_id: int) -> None:
        await self._conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        await self._conn.commit()

    async def delete_sessions_by_user(self, user_id: int) -> None:
        # messages 表有 ON DELETE CASCADE，删 sessions 会自动清理其消息
        await self._conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        await self._conn.commit()

    @staticmethod
    def _row_to_session(row: aiosqlite.Row) -> Session:
        return Session(
            id=row["id"], user_id=row["user_id"], title=row["title"],
            model_name=row["model_name"], preset_id=row["preset_id"],
            total_prompt_tokens=row["total_prompt_tokens"],
            total_completion_tokens=row["total_completion_tokens"],
            created_at=SQLiteBackend._str_to_dt(row["created_at"]),
            updated_at=SQLiteBackend._str_to_dt(row["updated_at"]),
        )

    # ── 消息相关 ──────────────────────────────────────────────────────────

    async def add_message(self, message: Message) -> Message:
        cursor = await self._conn.execute(
            """INSERT INTO messages (session_id, role, content, prompt_tokens,
               completion_tokens, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (message.session_id, message.role, message.content,
             message.prompt_tokens, message.completion_tokens,
             self._dt_to_str(message.created_at)),
        )
        await self._conn.commit()
        message.id = cursor.lastrowid
        return message

    async def list_messages(self, session_id: int) -> list[Message]:
        async with self._conn.execute(
            "SELECT * FROM messages WHERE session_id = ? ORDER BY id", (session_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [self._row_to_message(r) for r in rows]

    async def search_messages(self, user_id: int, keyword: str) -> list[Message]:
        # 联表查询：通过 messages 关联 sessions，找到属于该用户的消息
        async with self._conn.execute(
            """SELECT m.* FROM messages m
               JOIN sessions s ON m.session_id = s.id
               WHERE s.user_id = ? AND m.content LIKE ?
               ORDER BY m.id""",
            (user_id, f"%{keyword}%"),
        ) as cursor:
            rows = await cursor.fetchall()
            return [self._row_to_message(r) for r in rows]

    @staticmethod
    def _row_to_message(row: aiosqlite.Row) -> Message:
        return Message(
            id=row["id"], session_id=row["session_id"], role=row["role"],
            content=row["content"], prompt_tokens=row["prompt_tokens"],
            completion_tokens=row["completion_tokens"],
            created_at=SQLiteBackend._str_to_dt(row["created_at"]),
        )

    # ── 预设相关 ──────────────────────────────────────────────────────────

    async def get_preset_by_id(self, preset_id: int) -> Optional[Preset]:
        """按 ID 查询单个预设（含内置和所有用户的自定义）。不存在返回 None。"""
        async with self._conn.execute(
            "SELECT * FROM presets WHERE id = ?", (preset_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return self._row_to_preset(row) if row else None

    async def save_preset(self, preset: Preset) -> Preset:
        # if preset.id is None: # 无法判断并区分 id=0 的情况
        if not preset.id:
            # 新增（id 为 None 或 0 都视为新增）
            cursor = await self._conn.execute(
                """INSERT INTO presets (user_id, name, description, system_prompt,
                   is_builtin, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (preset.user_id, preset.name, preset.description, preset.system_prompt,
                 1 if preset.is_builtin else 0,
                 self._dt_to_str(preset.created_at), self._dt_to_str(preset.updated_at)),
            )
            await self._conn.commit()
            preset.id = cursor.lastrowid
        else:
            # 更新
            await self._conn.execute(
                """UPDATE presets SET name=?, description=?, system_prompt=?,
                   is_builtin=?, updated_at=? WHERE id=?""",
                (preset.name, preset.description, preset.system_prompt,
                 1 if preset.is_builtin else 0,
                 self._dt_to_str(preset.updated_at), preset.id),
            )
            await self._conn.commit()
        return preset

    async def list_presets(self, user_id: int) -> list[Preset]:
        # 系统内置（user_id IS NULL）+ 该用户的自定义（user_id = ?）
        async with self._conn.execute(
            """SELECT * FROM presets WHERE user_id IS NULL OR user_id = ? ORDER BY id""",
            (user_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [self._row_to_preset(r) for r in rows]

    async def delete_preset(self, preset_id: int) -> None:
        await self._conn.execute("DELETE FROM presets WHERE id = ?", (preset_id,))
        await self._conn.commit()

    @staticmethod
    def _row_to_preset(row: aiosqlite.Row) -> Preset:
        return Preset(
            id=row["id"], user_id=row["user_id"], name=row["name"],
            description=row["description"], system_prompt=row["system_prompt"],
            is_builtin=bool(row["is_builtin"]),
            created_at=SQLiteBackend._str_to_dt(row["created_at"]),
            updated_at=SQLiteBackend._str_to_dt(row["updated_at"]),
        )

    # ── 用户配置相关 ──────────────────────────────────────────────────────

    async def get_user_config(self, user_id: int, key: str) -> Optional[str]:
        async with self._conn.execute(
            "SELECT value FROM user_configs WHERE user_id = ? AND key = ?",
            (user_id, key),
        ) as cursor:
            row = await cursor.fetchone()
            return row["value"] if row else None

    async def set_user_config(self, config: UserConfig) -> None:
        # 先查是否已存在（user_id + key 视为唯一）
        async with self._conn.execute(
            "SELECT id FROM user_configs WHERE user_id = ? AND key = ?",
            (config.user_id, config.key),
        ) as cursor:
            existing = await cursor.fetchone()

        now_str = self._dt_to_str(config.updated_at)
        if existing:
            await self._conn.execute(
                "UPDATE user_configs SET value=?, updated_at=? WHERE id=?",
                (config.value, now_str, existing["id"]),
            )
        else:
            await self._conn.execute(
                """INSERT INTO user_configs (user_id, key, value, updated_at)
                   VALUES (?, ?, ?, ?)""",
                (config.user_id, config.key, config.value, now_str),
            )
        await self._conn.commit()