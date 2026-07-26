"""
行程规划策略模型 —— 成员三负责（v2 新增）
============================================

LLM 在生成行程前先输出 ItineraryPlanningPolicy，
声明规划策略，使规划过程可解释、可追溯。

这是 v2 "大模型主导行程组合" 架构的核心产物之一。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ItineraryPlanningPolicy(BaseModel):
    """LLM 在规划行程前输出的策略声明。

    声明内容由大模型结合用户隐含偏好生成，不由 Python 规则填充。
    """

    daily_themes: list[str] = Field(
        default_factory=list,
        description="每日主题，如 ['历史文化深度日', '皇家园林休闲日']",
    )
    pace_strategy: str = Field(
        default="normal",
        description="整体节奏策略: relaxed / normal / compact",
    )
    combination_rationale: str = Field(
        default="",
        description="为什么这些景点被分到同一天，组合逻辑",
    )
    priority_order: list[str] = Field(
        default_factory=list,
        description="规划时应用的优先级排序，如 ['必去景点', '兴趣匹配', '距离就近']",
    )
    buffer_minutes: int = Field(
        15, ge=0, le=120,
        description="活动之间缓冲时间（分钟）",
    )
    rest_strategy: str | None = Field(
        None,
        description="休息安排策略，如 '午餐后安排低强度活动作为休息'",
    )
    indoor_outdoor_balance: str | None = Field(
        None,
        description="室内外平衡策略，如 '下午优先安排室内景点避暑'",
    )
    walking_control_strategy: str | None = Field(
        None,
        description="步行控制策略，如 '通过公交替代长距离步行路段'",
    )
    notes: list[str] = Field(
        default_factory=list,
        description="其他规划备注",
    )
