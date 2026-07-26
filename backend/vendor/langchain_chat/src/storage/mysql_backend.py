"""MySQL 存储后端实现。

实现 StorageBackend 定义的全部接口方法，用 aiomysql 异步驱动操作 MySQL。
对应需求文档第四章「存储架构」（MySQL 为企业级部署后端）。

设计说明：
    - 用 aiomysql 异步访问数据库（项目全链路异步）。
    - 使用 DictCursor 按列名访问结果（与 SQLiteBackend 的 aiosqlite.Row 保持一致）。
    - datetime 字段以 ISO 格式字符串存储（与 SQLiteBackend 保持一致）。
    - 表结构使用 utf8mb4 字符集（支持中文和 emoji）。
    - 外键和级联删除与 SQLiteBackend 保持一致。
"""

from datetime import datetime, timezone
from typing import Optional

import aiomysql
from models.schemas import Message, Preset, Session, User, UserConfig
from storage.base import StorageBackend


class MySQLBackend(StorageBackend):
    """MySQL 存储后端。

    使用前必须先调用 initialize() 建库建表。
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 3306,
        user: str = "root",
        password: str = "",
        database: str = "langchain_chat",
    ):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.database = database
        self._conn: Optional[aiomysql.Connection] = None

    # ── 初始化与清理 ──────────────────────────────────────────────────────

    async def initialize(self) -> None:
        """初始化：先连 MySQL 服务器建库（如不存在），再连数据库建表。"""
        # 第一步：连接 MySQL 服务器（不指定数据库），创建数据库
        conn = await aiomysql.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            charset="utf8mb4",
        )
        async with conn.cursor() as cur:
            await cur.execute(
                f"CREATE DATABASE IF NOT EXISTS `{self.database}` "
                f"CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        conn.close()

        # 第二步：连接指定数据库
        self._conn = await aiomysql.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            db=self.database,
            charset="utf8mb4",
            autocommit=False,
        )

        # 建表
        await self._create_tables()

    async def close(self) -> None:
        """关闭连接。"""
        if self._conn:
            self._conn.close()
            self._conn = None

    async def _create_tables(self) -> None:
        """创建所有表（IF NOT EXISTS 保证可重复执行）。"""
        async with self._conn.cursor() as cur:
            await cur.execute(
                "SET FOREIGN_KEY_CHECKS=0"
            )  # 关闭外键检查（解决循环引用）
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INT PRIMARY KEY AUTO_INCREMENT,
                    username VARCHAR(255) UNIQUE NOT NULL,
                    default_model VARCHAR(255),
                    default_preset_id INT,
                    created_at VARCHAR(50) NOT NULL,
                    updated_at VARCHAR(50) NOT NULL
                ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            """)
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id INT PRIMARY KEY AUTO_INCREMENT,
                    user_id INT NOT NULL,
                    title VARCHAR(255) NOT NULL,
                    model_name VARCHAR(255) NOT NULL,
                    preset_id INT,
                    total_prompt_tokens INT NOT NULL DEFAULT 0,
                    total_completion_tokens INT NOT NULL DEFAULT 0,
                    created_at VARCHAR(50) NOT NULL,
                    updated_at VARCHAR(50) NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                    FOREIGN KEY (preset_id) REFERENCES presets(id)
                ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            """)
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INT PRIMARY KEY AUTO_INCREMENT,
                    session_id INT NOT NULL,
                    role VARCHAR(20) NOT NULL,
                    content TEXT NOT NULL,
                    prompt_tokens INT NOT NULL DEFAULT 0,
                    completion_tokens INT NOT NULL DEFAULT 0,
                    created_at VARCHAR(50) NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            """)
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS presets (
                    id INT PRIMARY KEY AUTO_INCREMENT,
                    user_id INT,
                    name VARCHAR(255) NOT NULL,
                    description VARCHAR(1000) NOT NULL DEFAULT '',
                    system_prompt TEXT NOT NULL,
                    is_builtin TINYINT(1) NOT NULL DEFAULT 0,
                    created_at VARCHAR(50) NOT NULL,
                    updated_at VARCHAR(50) NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            """)
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS user_configs (
                    id INT PRIMARY KEY AUTO_INCREMENT,
                    user_id INT NOT NULL,
                    `key` VARCHAR(255) NOT NULL,
                    value TEXT NOT NULL,
                    updated_at VARCHAR(50) NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            """)
            await cur.execute("SET FOREIGN_KEY_CHECKS=1")  # 恢复外键检查
        await self._conn.commit()

    # ── 辅助方法 ──────────────────────────────────────────────────────────

    @staticmethod
    def _dt_to_str(dt: datetime) -> str:
        return dt.isoformat()

    @staticmethod
    def _str_to_dt(s: str) -> datetime:
        return datetime.fromisoformat(s)

    def _cursor(self):
        """获取 DictCursor（按列名访问结果）。"""
        return self._conn.cursor(aiomysql.DictCursor)

    # ── 用户相关 ──────────────────────────────────────────────────────────

    async def create_user(self, user: User) -> User:
        async with self._cursor() as cur:
            await cur.execute(
                """INSERT INTO users (username, default_model, default_preset_id, created_at, updated_at)
                   VALUES (%s, %s, %s, %s, %s)""",
                (
                    user.username,
                    user.default_model,
                    user.default_preset_id,
                    self._dt_to_str(user.created_at),
                    self._dt_to_str(user.updated_at),
                ),
            )
            await self._conn.commit()
            user.id = cur.lastrowid
        return user

    async def get_user_by_name(self, username: str) -> Optional[User]:
        async with self._cursor() as cur:
            await cur.execute("SELECT * FROM users WHERE username = %s", (username,))
            row = await cur.fetchone()
            return self._row_to_user(row) if row else None

    async def list_users(self) -> list[User]:
        async with self._cursor() as cur:
            await cur.execute("SELECT * FROM users ORDER BY id")
            rows = await cur.fetchall()
            return [self._row_to_user(r) for r in rows]

    async def delete_user(self, user_id: int) -> None:
        async with self._cursor() as cur:
            await cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
            await self._conn.commit()

    async def update_user(self, user: User) -> None:
        async with self._cursor() as cur:
            await cur.execute(
                """UPDATE users SET username=%s, default_model=%s, default_preset_id=%s,
                   updated_at=%s WHERE id=%s""",
                (
                    user.username,
                    user.default_model,
                    user.default_preset_id,
                    self._dt_to_str(user.updated_at),
                    user.id,
                ),
            )
            await self._conn.commit()

    @staticmethod
    def _row_to_user(row: dict) -> User:
        return User(
            id=row["id"],
            username=row["username"],
            default_model=row["default_model"],
            default_preset_id=row["default_preset_id"],
            created_at=MySQLBackend._str_to_dt(row["created_at"]),
            updated_at=MySQLBackend._str_to_dt(row["updated_at"]),
        )

    # ── 会话相关 ──────────────────────────────────────────────────────────

    async def create_session(self, session: Session) -> Session:
        async with self._cursor() as cur:
            await cur.execute(
                """INSERT INTO sessions (user_id, title, model_name, preset_id,
                   total_prompt_tokens, total_completion_tokens, created_at, updated_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    session.user_id,
                    session.title,
                    session.model_name,
                    session.preset_id,
                    session.total_prompt_tokens,
                    session.total_completion_tokens,
                    self._dt_to_str(session.created_at),
                    self._dt_to_str(session.updated_at),
                ),
            )
            await self._conn.commit()
            session.id = cur.lastrowid
        return session

    async def get_session(self, session_id: int) -> Optional[Session]:
        async with self._cursor() as cur:
            await cur.execute("SELECT * FROM sessions WHERE id = %s", (session_id,))
            row = await cur.fetchone()
            return self._row_to_session(row) if row else None

    async def list_sessions(
        self, user_id: int, limit: int = 0, offset: int = 0
    ) -> list[Session]:
        async with self._cursor() as cur:
            if limit > 0:
                await cur.execute(
                    "SELECT * FROM sessions WHERE user_id = %s ORDER BY id DESC LIMIT %s OFFSET %s",
                    (user_id, limit, offset),
                )
            else:
                await cur.execute(
                    "SELECT * FROM sessions WHERE user_id = %s ORDER BY id DESC",
                    (user_id,),
                )
            rows = await cur.fetchall()
            return [self._row_to_session(r) for r in rows]

    async def update_session(self, session: Session) -> None:
        session.updated_at = datetime.now(timezone.utc)
        async with self._cursor() as cur:
            await cur.execute(
                """UPDATE sessions SET title=%s, model_name=%s, preset_id=%s,
                   total_prompt_tokens=%s, total_completion_tokens=%s, updated_at=%s WHERE id=%s""",
                (
                    session.title,
                    session.model_name,
                    session.preset_id,
                    session.total_prompt_tokens,
                    session.total_completion_tokens,
                    self._dt_to_str(session.updated_at),
                    session.id,
                ),
            )
            await self._conn.commit()

    async def delete_session(self, session_id: int) -> None:
        async with self._cursor() as cur:
            await cur.execute("DELETE FROM sessions WHERE id = %s", (session_id,))
            await self._conn.commit()

    async def delete_sessions_by_user(self, user_id: int) -> None:
        async with self._cursor() as cur:
            await cur.execute("DELETE FROM sessions WHERE user_id = %s", (user_id,))
            await self._conn.commit()

    @staticmethod
    def _row_to_session(row: dict) -> Session:
        return Session(
            id=row["id"],
            user_id=row["user_id"],
            title=row["title"],
            model_name=row["model_name"],
            preset_id=row["preset_id"],
            total_prompt_tokens=row["total_prompt_tokens"],
            total_completion_tokens=row["total_completion_tokens"],
            created_at=MySQLBackend._str_to_dt(row["created_at"]),
            updated_at=MySQLBackend._str_to_dt(row["updated_at"]),
        )

    # ── 消息相关 ──────────────────────────────────────────────────────────

    async def add_message(self, message: Message) -> Message:
        async with self._cursor() as cur:
            await cur.execute(
                """INSERT INTO messages (session_id, role, content, prompt_tokens,
                   completion_tokens, created_at)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (
                    message.session_id,
                    message.role,
                    message.content,
                    message.prompt_tokens,
                    message.completion_tokens,
                    self._dt_to_str(message.created_at),
                ),
            )
            await self._conn.commit()
            message.id = cur.lastrowid
        return message

    async def list_messages(self, session_id: int) -> list[Message]:
        async with self._cursor() as cur:
            await cur.execute(
                "SELECT * FROM messages WHERE session_id = %s ORDER BY id",
                (session_id,),
            )
            rows = await cur.fetchall()
            return [self._row_to_message(r) for r in rows]

    async def search_messages(self, user_id: int, keyword: str) -> list[Message]:
        async with self._cursor() as cur:
            await cur.execute(
                """SELECT m.* FROM messages m
                   JOIN sessions s ON m.session_id = s.id
                   WHERE s.user_id = %s AND m.content LIKE %s
                   ORDER BY m.id""",
                (user_id, f"%{keyword}%"),
            )
            rows = await cur.fetchall()
            return [self._row_to_message(r) for r in rows]

    @staticmethod
    def _row_to_message(row: dict) -> Message:
        return Message(
            id=row["id"],
            session_id=row["session_id"],
            role=row["role"],
            content=row["content"],
            prompt_tokens=row["prompt_tokens"],
            completion_tokens=row["completion_tokens"],
            created_at=MySQLBackend._str_to_dt(row["created_at"]),
        )

    # ── 预设相关 ──────────────────────────────────────────────────────────

    async def get_preset_by_id(self, preset_id: int) -> Optional[Preset]:
        async with self._cursor() as cur:
            await cur.execute("SELECT * FROM presets WHERE id = %s", (preset_id,))
            row = await cur.fetchone()
            return self._row_to_preset(row) if row else None

    async def save_preset(self, preset: Preset) -> Preset:
        async with self._cursor() as cur:
            if not preset.id:
                await cur.execute(
                    """INSERT INTO presets (user_id, name, description, system_prompt,
                       is_builtin, created_at, updated_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                    (
                        preset.user_id,
                        preset.name,
                        preset.description,
                        preset.system_prompt,
                        1 if preset.is_builtin else 0,
                        self._dt_to_str(preset.created_at),
                        self._dt_to_str(preset.updated_at),
                    ),
                )
                await self._conn.commit()
                preset.id = cur.lastrowid
            else:
                await cur.execute(
                    """UPDATE presets SET name=%s, description=%s, system_prompt=%s,
                       is_builtin=%s, updated_at=%s WHERE id=%s""",
                    (
                        preset.name,
                        preset.description,
                        preset.system_prompt,
                        1 if preset.is_builtin else 0,
                        self._dt_to_str(preset.updated_at),
                        preset.id,
                    ),
                )
                await self._conn.commit()
        return preset

    async def list_presets(self, user_id: int) -> list[Preset]:
        async with self._cursor() as cur:
            await cur.execute(
                """SELECT * FROM presets WHERE user_id IS NULL OR user_id = %s ORDER BY id""",
                (user_id,),
            )
            rows = await cur.fetchall()
            return [self._row_to_preset(r) for r in rows]

    async def delete_preset(self, preset_id: int) -> None:
        async with self._cursor() as cur:
            await cur.execute("DELETE FROM presets WHERE id = %s", (preset_id,))
            await self._conn.commit()

    @staticmethod
    def _row_to_preset(row: dict) -> Preset:
        return Preset(
            id=row["id"],
            user_id=row["user_id"],
            name=row["name"],
            description=row["description"],
            system_prompt=row["system_prompt"],
            is_builtin=bool(row["is_builtin"]),
            created_at=MySQLBackend._str_to_dt(row["created_at"]),
            updated_at=MySQLBackend._str_to_dt(row["updated_at"]),
        )

    # ── 用户配置相关 ──────────────────────────────────────────────────────

    async def get_user_config(self, user_id: int, key: str) -> Optional[str]:
        async with self._cursor() as cur:
            await cur.execute(
                "SELECT value FROM user_configs WHERE user_id = %s AND `key` = %s",
                (user_id, key),
            )
            row = await cur.fetchone()
            return row["value"] if row else None

    async def set_user_config(self, config: UserConfig) -> None:
        async with self._cursor() as cur:
            await cur.execute(
                "SELECT id FROM user_configs WHERE user_id = %s AND `key` = %s",
                (config.user_id, config.key),
            )
            existing = await cur.fetchone()

            now_str = self._dt_to_str(config.updated_at)
            if existing:
                await cur.execute(
                    "UPDATE user_configs SET value=%s, updated_at=%s WHERE id=%s",
                    (config.value, now_str, existing["id"]),
                )
            else:
                await cur.execute(
                    """INSERT INTO user_configs (user_id, `key`, value, updated_at)
                       VALUES (%s, %s, %s, %s)""",
                    (config.user_id, config.key, config.value, now_str),
                )
            await self._conn.commit()
