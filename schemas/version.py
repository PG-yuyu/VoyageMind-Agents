"""
版本差异模型 —— 成员三负责
============================

每次修改生成新版本，不覆盖旧版本。TripDiff 用于修改前后对比展示。
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class ChangeType(str, Enum):
    REPLACE = "replace"
    DELETE = "delete"
    ADD = "add"
    REORDER = "reorder"


class TripChange(BaseModel):
    """单条变更记录。"""

    change_type: ChangeType = Field(..., description="变更类型")
    before_item_id: str | None = None
    after_item_id: str | None = None
    before_place_id: str | None = None
    after_place_id: str | None = None
    reason: str | None = Field(None, description="变更原因")
    cost_change: float = Field(0.0, description="费用变动（元），负=省钱")
    distance_change_m: int = Field(0, description="距离变动（米），负=缩短")


class TripDiff(BaseModel):
    """版本间差异对比。"""

    from_version: int = Field(..., ge=1)
    to_version: int = Field(..., ge=1)
    affected_days: list[int] = Field(default_factory=list)
    changes: list[TripChange] = Field(default_factory=list)
    unchanged_item_ids: list[str] = Field(default_factory=list)
