"""
规划状态机
==========

追踪行程规划的完整状态流转：
  preference_interpretation → planning → validating → repairing (loop) → preference_check → optimizing (loop) → completed

状态字段承载每个阶段的输入和输出，支持断点恢复和日志记录。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class PlanningPhase(str, Enum):
    """规划阶段枚举。"""

    INIT = "init"
    PREFERENCE_INTERPRETATION = "preference_interpretation"
    ITINERARY_PLANNING = "itinerary_planning"
    HARD_VALIDATING = "hard_validating"
    HARD_REPAIRING = "hard_repairing"
    SOFT_EVALUATING = "soft_evaluating"
    SOFT_OPTIMIZING = "soft_optimizing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class PlanningState:
    """行程规划状态机。

    Attributes:
        phase: 当前阶段
        session_id: 会话 ID
        requirements: TravelRequest 字典
        recommendation_context: 完整 RecommendationContext
        recommendation_policy: 推荐策略
        places: 候选地点列表
        routes: 路线列表
        hard_constraints: 明确硬约束
        semantic_preferences: 隐含偏好
        planning_policy: LLM 生成的行程规划策略
        itinerary: 当前行程（逐步迭代完善）
        hard_evaluation: 硬约束校验结果
        soft_evaluation: 软偏好评价结果
        repair_count: 已执行的硬约束修复次数
        optimize_count: 已执行的软偏好优化次数
        max_repairs: 最大硬约束修复次数（默认 2）
        max_optimizes: 最大软偏好优化次数（默认 1）
        errors: 错误记录
        trace_steps: Agent 执行轨迹
    """

    # --- 标识 ---
    phase: PlanningPhase = PlanningPhase.INIT
    session_id: str = ""

    # --- 输入 ---
    requirements: dict[str, Any] = field(default_factory=dict)
    recommendation_context: dict[str, Any] = field(default_factory=dict)
    recommendation_policy: dict[str, Any] = field(default_factory=dict)
    places: list[dict[str, Any]] = field(default_factory=list)
    routes: list[dict[str, Any]] = field(default_factory=list)
    hard_constraints: list[dict[str, Any]] = field(default_factory=list)
    semantic_preferences: list[dict[str, Any]] = field(default_factory=list)

    # --- 各阶段产物 ---
    planning_policy: dict[str, Any] | None = None
    itinerary: dict[str, Any] | None = None
    hard_evaluation: dict[str, Any] | None = None
    soft_evaluation: dict[str, Any] | None = None

    # --- 循环控制 ---
    repair_count: int = 0
    optimize_count: int = 0
    max_repairs: int = 2
    max_optimizes: int = 1

    # --- 错误 ---
    errors: list[str] = field(default_factory=list)

    # --- 执行轨迹 ---
    trace_steps: list[dict[str, Any]] = field(default_factory=list)

    # ------------------------------------------------------------------
    # 阶段转换
    # ------------------------------------------------------------------

    def transition_to(self, phase: PlanningPhase) -> None:
        """切换到指定阶段并记录轨迹。"""
        old = self.phase.value
        self.phase = phase
        self.trace_steps.append({
            "step": len(self.trace_steps) + 1,
            "agent": "planning_agent",
            "action": f"{old} → {phase.value}",
            "summary": phase.value,
            "status": "success",
        })

    def add_error(self, message: str) -> None:
        """记录错误并标记为 FAILED。"""
        self.errors.append(message)
        self.phase = PlanningPhase.FAILED
        self.trace_steps.append({
            "step": len(self.trace_steps) + 1,
            "agent": "planning_agent",
            "action": "error",
            "summary": message,
            "status": "error",
        })

    def can_repair(self) -> bool:
        """是否还可以进行硬约束修复。"""
        return self.repair_count < self.max_repairs

    def can_optimize(self) -> bool:
        """是否还可以进行软偏好优化。"""
        return self.optimize_count < self.max_optimizes

    @property
    def is_completed(self) -> bool:
        return self.phase in (PlanningPhase.COMPLETED, PlanningPhase.FAILED)

    # ------------------------------------------------------------------
    # 序列化
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """转为字典（用于序列化/日志）。"""
        return {
            "phase": self.phase.value,
            "session_id": self.session_id,
            "repair_count": self.repair_count,
            "optimize_count": self.optimize_count,
            "errors": self.errors,
            "trace_steps": self.trace_steps,
            "has_policy": self.planning_policy is not None,
            "has_itinerary": self.itinerary is not None,
            "hard_passed": self.hard_evaluation.get("passed") if self.hard_evaluation else None,
            "soft_passed": self.soft_evaluation.get("soft_preference_passed") if self.soft_evaluation else None,
        }

    def get_planning_context(self) -> dict[str, Any]:
        """构建传递给 LLM 和工具的完整上下文。"""
        return {
            "requirements": self.requirements,
            "recommendation_context": self.recommendation_context,
            "recommendation_policy": self.recommendation_policy,
            "places": self.places,
            "routes": self.routes,
            "hard_constraints": self.hard_constraints,
            "semantic_preferences": self.semantic_preferences,
            "planning_policy": self.planning_policy,
        }
