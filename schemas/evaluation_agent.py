"""
评价系统 Agent 统一输出模型
============================

将硬约束校验（HardConstraintValidator）和软偏好评价（ItineraryPreferenceCritic）
的输出合并为一个统一的评价结果，并添加重规划指导指令（ReplanDirectives）。

设计依据: docs/评价系统AGENT.md — 双轨并行评价机制
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from schemas.evaluation import EvaluationMetrics, ValidationIssue, ValidationCode
from schemas.preference_evaluation import SoftPreferenceIssue, SoftPreferenceEvaluation


# ── 重规划指导指令 ──────────────────────────────────────────────────────────


class ReplanActionType(str, Enum):
    """重规划动作类型。"""

    REPLACE = "replace"
    REMOVE = "remove"
    RESCHEDULE = "reschedule"
    ADD_BUFFER = "add_buffer"
    REDUCE_INTENSITY = "reduce_intensity"
    CHANGE_MODE = "change_mode"
    ADJUST_TIME = "adjust_time"
    SPLIT_DAY = "split_day"
    MERGE_DAY = "merge_day"


class ReplanDirective(BaseModel):
    """针对某个日期/项目的重规划指导指令。

    该指令由评价 Agent 的 LLM 综合分析后生成，
    供 AdjustmentAgent 或动态调整 Agent 执行。
    """

    target_day: int = Field(..., description="目标日期（第几天）")
    target_item_ids: list[str] = Field(
        default_factory=list,
        description="受影响的具体行程项 ID 列表（空表示整日调整）",
    )
    action: ReplanActionType = Field(
        ...,
        description="重规划动作类型",
    )
    reason: str = Field(
        ...,
        description="触发该指令的原因（关联哪个校验问题）",
    )
    suggestion: str = Field(
        ...,
        description="具体的修改方向，如'移除远郊景点X，将晚餐延后30分钟'",
    )
    priority: int = Field(
        default=1,
        ge=1, le=3,
        description="优先级: 1=高(阻断级) 2=中(建议级) 3=低(可忽略)",
    )

    @property
    def is_high_priority(self) -> bool:
        return self.priority == 1


# ── 综合评价结果 ────────────────────────────────────────────────────────────


class OverallEvaluationResult(BaseModel):
    """评价系统 Agent 的最终综合输出。

    融合了硬约束校验和软偏好评价，并提供重规划指令。
    """

    # ── 综合状态 ──────────────────────────────────────────────────────
    passed: bool = Field(
        ...,
        description="整体是否通过（硬约束无error 且 软偏好关键项满足）",
    )
    soft_preference_passed: bool = Field(
        ...,
        description="软偏好体验是否达标",
    )
    overall_score: float = Field(
        ...,
        ge=0.0, le=1.0,
        description="基于 5 项客观量化指标的综合评分",
    )

    # ── 分级问题列表 ──────────────────────────────────────────────────
    hard_issues: list[ValidationIssue] = Field(
        default_factory=list,
        description="阻断级/硬约束问题",
    )
    soft_issues: list[SoftPreferenceIssue] = Field(
        default_factory=list,
        description="建议级/软偏好问题",
    )

    # ── 5 大客观量化指标（扩展版） ─────────────────────────────────────
    metrics: EvaluationMetrics = Field(
        default_factory=EvaluationMetrics,
        description="5 大客观量化指标",
    )
    time_reasonableness_score: float = Field(
        1.0,
        ge=0.0, le=1.0,
        description="时间合理性得分（新增第5项指标）",
    )

    # ── 重规划指导指令 ────────────────────────────────────────────────
    replan_directives: list[ReplanDirective] = Field(
        default_factory=list,
        description="给动态调整 Agent 的重规划指令列表",
    )

    # ── 源数据（可选，供追溯） ─────────────────────────────────────────
    hard_evaluation_raw: dict[str, Any] | None = Field(
        None,
        description="硬约束校验原始结果",
    )
    soft_evaluation_raw: dict[str, Any] | None = Field(
        None,
        description="软偏好评价原始结果",
    )

    # ── 辅助属性 ──────────────────────────────────────────────────────
    @property
    def hard_issue_count(self) -> int:
        return len(self.hard_issues)

    @property
    def soft_issue_count(self) -> int:
        return len(self.soft_issues)

    @property
    def total_issue_count(self) -> int:
        return self.hard_issue_count + self.soft_issue_count

    @property
    def has_error_issues(self) -> bool:
        """是否有 error 级别的硬约束问题。"""
        from schemas.common import Severity
        return any(i.severity == Severity.ERROR for i in self.hard_issues)

    def to_summary_dict(self) -> dict[str, Any]:
        """转为简要摘要字典（用于日志/前端展示）。"""
        return {
            "passed": self.passed,
            "soft_preference_passed": self.soft_preference_passed,
            "overall_score": round(self.overall_score, 2),
            "hard_issues": self.hard_issue_count,
            "soft_issues": self.soft_issue_count,
            "replan_directives": len(self.replan_directives),
            "metrics": self.metrics.model_dump(),
        }

