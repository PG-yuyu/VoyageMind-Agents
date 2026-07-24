"""存储后端抽象基类（接口定义）。

本模块定义所有存储后端（SQLite、MySQL、File）必须实现的接口契约。
对应需求文档第四章「存储架构」（可插拔存储后端）。

设计说明：
    - 采用 ABC（抽象基类）强制子类实现所有方法，保证接口一致性。
    - 所有方法都是 async 的，因为本项目全链路异步（需求 A3）。
    - 本步骤只定义接口，不实现具体读写逻辑（Step 3 实现 SQLite 后端）。
"""

from abc import ABC, abstractmethod
from typing import Optional

from models.schemas import Message, Preset, Session, User, UserConfig


class StorageBackend(ABC):
    """存储后端抽象基类。

    所有具体的存储后端（SQLiteBackend、MySQLBackend、FileBackend）
    必须继承本类并实现所有 abstractmethod。
    如果子类漏实现某个方法，在实例化时会立即抛出 TypeError，及早暴露问题。
    """

    # ── 初始化与清理 ──────────────────────────────────────────────────────

    @abstractmethod
    async def initialize(self) -> None:
        """初始化存储后端（如建表、建连接）。在程序启动时调用一次。"""
        ...

    @abstractmethod
    async def close(self) -> None:
        """关闭存储后端（如关闭数据库连接）。在程序退出时调用。"""
        ...

    # ── 用户相关 ──────────────────────────────────────────────────────────

    @abstractmethod
    async def create_user(self, user: User) -> User:
        """创建用户。返回创建后的 User（含分配的 id）。"""
        ...

    @abstractmethod
    async def get_user_by_name(self, username: str) -> Optional[User]:
        """按用户名查询用户。不存在返回 None。"""
        ...

    @abstractmethod
    async def list_users(self) -> list[User]:
        """列出所有用户。"""
        ...

    @abstractmethod
    async def delete_user(self, user_id: int) -> None:
        """删除用户及其所有关联数据（会话、消息、预设、配置）。"""
        ...

    # ── 会话相关 ──────────────────────────────────────────────────────────

    @abstractmethod
    async def create_session(self, session: Session) -> Session:
        """创建会话。返回创建后的 Session。"""
        ...

    @abstractmethod
    async def get_session(self, session_id: int) -> Optional[Session]:
        """按 ID 查询会话。不存在返回 None。"""
        ...

    @abstractmethod
    async def list_sessions(self, user_id: int, limit: int = 0, offset: int = 0) -> list[Session]:
        """列出指定用户的会话（支持分页）。

        参数：
            user_id: 用户 ID
            limit: 返回数量上限（0=不限制）
            offset: 跳过前 N 条（默认 0）
        """
        ...

    @abstractmethod
    async def update_session(self, session: Session) -> None:
        """更新会话（标题、token 用量等）。"""
        ...

    @abstractmethod
    async def delete_session(self, session_id: int) -> None:
        """删除会话及其所有消息。"""
        ...

    @abstractmethod
    async def delete_sessions_by_user(self, user_id: int) -> None:
        """删除指定用户的全部会话及其所有消息。"""
        ...

    # ── 消息相关 ──────────────────────────────────────────────────────────

    @abstractmethod
    async def add_message(self, message: Message) -> Message:
        """添加一条消息。返回创建后的 Message。"""
        ...

    @abstractmethod
    async def list_messages(self, session_id: int) -> list[Message]:
        """列出指定会话的所有消息，按时间正序。"""
        ...

    @abstractmethod
    async def search_messages(self, user_id: int, keyword: str) -> list[Message]:
        """在指定用户的所有会话中按关键词搜索消息（需求 E1）。"""
        ...

    # ── 预设相关 ──────────────────────────────────────────────────────────

    @abstractmethod
    async def get_preset_by_id(self, preset_id: int) -> Optional[Preset]:
        """按 ID 查询单个预设（含内置和所有用户的自定义）。不存在返回 None。"""
        ...

    @abstractmethod
    async def save_preset(self, preset: Preset) -> Preset:
        """保存预设（新增或更新）。"""
        ...

    @abstractmethod
    async def list_presets(self, user_id: int) -> list[Preset]:
        """列出系统内置预设加指定用户的自定义预设。"""
        ...

    @abstractmethod
    async def delete_preset(self, preset_id: int) -> None:
        """删除预设（仅允许删除非内置的）。"""
        ...

    @abstractmethod
    async def update_user(self, user: User) -> None:
        """更新用户信息（如 default_model）。"""
        ...

    # ── 用户配置相关 ──────────────────────────────────────────────────────

    @abstractmethod
    async def get_user_config(self, user_id: int, key: str) -> Optional[str]:
        """读取用户配置值。不存在返回 None。"""
        ...

    @abstractmethod
    async def set_user_config(self, config: UserConfig) -> None:
        """写入用户配置值（新增或更新）。"""
        ...