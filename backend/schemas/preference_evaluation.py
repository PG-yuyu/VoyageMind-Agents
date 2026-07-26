"""
软偏好评价模型 —— 成员三负责（v2 新增）
============================================

ItineraryPreferenceCritic（LLM）对行程的隐含偏好满足度进行评价。

与 HardConstraintEvaluation（Python 规则）互补：
- Hard: 开放时间、预算上限、步行上限、必去景点 → Python
- Soft: 是否太累、是否同质化、是否体现当地特色 → LLM
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class SoftPreferenceIssue(BaseModel):
    """单条软偏好评价。"""

    preference: str = Field(
        ...,
        description="被评价的软偏好，如 '行程不要太累'",
    )
    assessment: str = Field(
        ...,
        description="对满足程度的评估，如 '第二天连续三个高步行强度景点'",
    )
    suggestion: str = Field(
        ...,
        description="优化建议，如 '删除一个次要景点并增加休息时间'",
    )
    confidence: float = Field(
        ...,
        ge=0.0, le=1.0,
        description="评估置信度",
    )


class SoftPreferenceEvaluation(BaseModel):
    """LLM 对行程软偏好满足度的综合评价。"""

    soft_preference_passed: bool = Field(
        ...,
        description="是否所有关键软偏好均满足",
    )
    issues: list[SoftPreferenceIssue] = Field(
        default_factory=list,
        description="不满足的软偏好及评估",
    )
    overall_assessment: str | None = Field(
        None,
        description="整体评价，如 '行程整体合理但第二天偏累'",
    )
