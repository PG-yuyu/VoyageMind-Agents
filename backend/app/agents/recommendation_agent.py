"""成员二旅游资源推荐 Agent。"""

from __future__ import annotations

from collections.abc import Iterable

from backend.app.schemas import (
    Place,
    RecommendationContext,
    RecommendationResult,
    ValidationIssue,
)
from backend.app.services import CandidateContextBuilder

from .recommendation_policy_agent import RecommendationPolicyAgent


class RecommendationAgent:
    """根据推荐上下文生成景点、酒店和餐厅候选推荐结果。"""

    DEFAULT_TYPE_LIMITS = {
        "attraction": 3,
        "hotel": 1,
        "restaurant": 2,
    }

    def __init__(
        self,
        policy_agent: RecommendationPolicyAgent | None = None,
        candidate_builder: CandidateContextBuilder | None = None,
        per_type_limit: int | None = None,
        per_type_limits: dict[str, int] | None = None,
    ) -> None:
        """注入策略生成器和候选资源构建器。"""

        if per_type_limit is not None and per_type_limit <= 0:
            raise ValueError("每类推荐数量必须大于 0")
        if per_type_limits is not None:
            for limit in per_type_limits.values():
                if limit <= 0:
                    raise ValueError("每类推荐数量必须大于 0")

        self.policy_agent = policy_agent or RecommendationPolicyAgent()
        self.candidate_builder = candidate_builder or CandidateContextBuilder()
        if per_type_limits is not None:
            self.per_type_limits = dict(per_type_limits)
        elif per_type_limit is not None:
            self.per_type_limits = {
                place_type: per_type_limit
                for place_type in self.DEFAULT_TYPE_LIMITS
            }
        else:
            self.per_type_limits = dict(self.DEFAULT_TYPE_LIMITS)

    def recommend(self, context: RecommendationContext) -> RecommendationResult:
        """执行第六步推荐流程，返回候选资源推荐结果。"""

        if not isinstance(context, RecommendationContext):
            raise TypeError("推荐 Agent 只能处理 RecommendationContext")

        policy = self.policy_agent.generate_policy(context)
        candidates = self.candidate_builder.build(
            policy=policy,
            city=context.requirements.city,
            per_type_limit=self.per_type_limits,
        )
        validation_issues = self._build_validation_issues(
            attractions=candidates.attractions,
            hotels=candidates.hotels,
            restaurants=candidates.restaurants,
        )
        need_follow_up = any(issue.level == "warning" for issue in validation_issues)

        return RecommendationResult(
            policy_summary=self._build_policy_summary(context, policy.focus),
            attractions=candidates.attractions,
            hotels=candidates.hotels,
            restaurants=candidates.restaurants,
            routes=[],
            evidence=[],
            validation_issues=validation_issues,
            need_follow_up=need_follow_up,
            follow_up_question=(
                "当前样例数据不足，是否可以放宽标签、区域或价格条件？"
                if need_follow_up
                else None
            ),
            agent_trace=[
                "接收成员一传入的 RecommendationContext",
                "调用 RecommendationPolicyAgent 生成推荐策略",
                f"查询景点候选资源 {len(candidates.attractions)} 个",
                f"查询酒店候选资源 {len(candidates.hotels)} 个",
                f"查询餐厅候选资源 {len(candidates.restaurants)} 个",
                "组装 RecommendationResult，不生成路线、地图或 RAG 证据",
            ],
        )

    def generate_recommendation(
        self, context: RecommendationContext
    ) -> RecommendationResult:
        """兼容更直观的方法名，内部复用 recommend。"""

        return self.recommend(context)

    def generate_result(self, context: RecommendationContext) -> RecommendationResult:
        """兼容结果生成命名，内部复用 recommend。"""

        return self.recommend(context)

    def run(self, context: RecommendationContext) -> RecommendationResult:
        """兼容工作流调用命名，内部复用 recommend。"""

        return self.recommend(context)

    def _build_policy_summary(
        self, context: RecommendationContext, focus: Iterable[str]
    ) -> str:
        """把策略重点压缩成结果摘要，供后续路线和行程模块读取。"""

        focus_text = "；".join(focus)
        return (
            f"面向{context.requirements.city}{context.requirements.days}日游，"
            f"按策略筛选景点、酒店和餐厅候选资源：{focus_text}"
        )

    def _build_validation_issues(
        self,
        attractions: list[Place],
        hotels: list[Place],
        restaurants: list[Place],
    ) -> list[ValidationIssue]:
        """记录每类候选资源是否足够，避免静默返回空结果。"""

        issues: list[ValidationIssue] = []
        if not attractions:
            issues.append(
                ValidationIssue(
                    field="attractions",
                    message="未查询到符合策略的景点候选资源",
                    level="warning",
                )
            )
        if not hotels:
            issues.append(
                ValidationIssue(
                    field="hotels",
                    message="未查询到符合策略的酒店候选资源",
                    level="warning",
                )
            )
        if not restaurants:
            issues.append(
                ValidationIssue(
                    field="restaurants",
                    message="未查询到符合策略的餐厅候选资源",
                    level="warning",
                )
            )
        return issues


ResourceRecommendationAgent = RecommendationAgent

__all__ = ["RecommendationAgent", "ResourceRecommendationAgent"]
