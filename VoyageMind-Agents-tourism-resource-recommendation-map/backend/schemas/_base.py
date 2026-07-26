"""
统一基类模型
============

成员一和成员三共用的基础模型。
ApiResponse 统一版：使用成员三的泛型 + 成员一的默认值。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Generic, TypeVar
from uuid import uuid4

from pydantic import BaseModel, Field

T = TypeVar("T")


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


class ApiResponse(BaseModel, Generic[T]):
    """
    统一响应封装。

    整合：
    - 成员三的泛型 data[T]（类型安全）
    - 成员一的 success/trace_id/timestamp 默认值（向后兼容）
    """

    success: bool = True
    code: str = "OK"
    message: str = "操作成功"
    data: T | None = None
    trace_id: str = Field(default_factory=lambda: new_id("trace"))
    timestamp: str = Field(default_factory=now_iso)


class PaginatedResponse(BaseModel, Generic[T]):
    """分页响应（成员三）。"""

    items: list[T] = Field(default_factory=list)
    page: int = 1
    page_size: int = 20
    total: int = 0
    has_more: bool = False
