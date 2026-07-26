"""用户管理业务层。

封装用户相关的业务逻辑：创建、查询、切换、删除。
对应需求文档 B1 至 B4（用户管理）。

设计说明：
    - UserManager 不直接操作数据库，而是依赖 StorageBackend 抽象。
    - 这样切换存储后端时，UserManager 无需修改。
    - 业务层负责：参数校验、错误处理、业务规则（如用户名唯一）。
"""

import logging

logger = logging.getLogger(__name__)
from typing import Optional

from models.schemas import User
from storage.base import StorageBackend


class UserManager:
    """用户管理器。

    通过传入的 StorageBackend 实例操作数据。
    使用方式：
        mgr = UserManager(backend)
        user = await mgr.create_user("alice")
    """

    def __init__(self, backend: StorageBackend):
        self.backend = backend

    async def create_user(
        self, username: str, default_model: Optional[str] = None
    ) -> User:
        """创建用户（B1）。用户名唯一校验。

        参数：
            username: 用户名
            default_model: 默认模型（可选）
        返回：
            创建后的 User
        异常：
            ValueError: 用户名为空 或 用户名已存在
        """
        # 参数校验：用户名非空
        if not username or not username.strip():
            raise ValueError("用户名不能为空")
        username = username.strip()

        # 业务规则：用户名唯一
        existing = await self.backend.get_user_by_name(username)
        if existing is not None:
            raise ValueError(f"用户名 '{username}' 已存在")

        # 创建
        user = User(id=0, username=username, default_model=default_model)
        logger.info("创建用户: %s", username)
        return await self.backend.create_user(user)

    async def get_user(self, username: str) -> Optional[User]:
        """按用户名查询用户。不存在返回 None。"""
        return await self.backend.get_user_by_name(username)

    async def list_users(self) -> list[User]:
        """列出所有用户。"""
        return await self.backend.list_users()

    async def delete_user(self, user_id: int) -> None:
        """删除用户（B3）。关联数据靠 CASCADE 自动清理。"""
        await self.backend.delete_user(user_id)

    async def user_exists(self, username: str) -> bool:
        """判断用户名是否存在。"""
        return await self.get_user(username) is not None

    async def update_user(self, user: User) -> None:
        """更新用户信息（如 default_model）。

        参数：
            user: 要更新的 User 对象（含最新的字段值）
        """
        await self.backend.update_user(user)
