"""
修改请求模型 —— 成员三负责
============================

成员一解析用户修改意图后，生成 ModificationRequest 交给成员三执行。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ModificationRequest(BaseModel):
    """用户主动修改行程的请求。"""

    session_id: str = Field(..., description="会话 ID")
    itinerary_id: str = Field(..., description="目标行程 ID")
    base_version: int = Field(..., ge=1, description="基于哪个版本修改")
    target_day: int | None = Field(None, ge=1, description="目标第几天")
    target_item_id: str | None = Field(None, description="目标行程项 ID")
    action: str = Field(..., description="修改动作, 如 change_to_indoor / replace_attraction")
    new_constraints: dict[str, Any] = Field(default_factory=dict)
    original_text: str | None = Field(None, description="用户原始输入")
    current_itinerary: dict[str, Any] | None = Field(
        None, description="当前完整行程 dict，传入后跳过版本库查询"
    )
