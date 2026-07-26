"""成员一调用成员二推荐模块的集成服务。"""

from __future__ import annotations

from dataclasses import asdict, replace
from typing import Any, Protocol

from backend.app.agents import RecommendationAgent
from backend.app.schemas import (
    RecommendationContext,
    RecommendationResult,
    SemanticPreference,
)
from backend.app.services import EvidenceEnrichmentService, MapDataService, RouteService
from backend.schemas import Assumption, TravelRequest


class RecommendationAgentLike(Protocol):
    """成员二推荐 Agent 需要提供的最小接口。"""

    def recommend(self, context: RecommendationContext) -> RecommendationResult:
        """根据推荐上下文生成景点、酒店和餐厅推荐结果。"""


class EvidenceServiceLike(Protocol):
    """RAG 依据补充服务需要提供的最小接口。"""

    def enrich_result(self, result: RecommendationResult) -> RecommendationResult:
        """为推荐结果补充可追溯依据。"""


class RouteServiceLike(Protocol):
    """路线服务需要提供的最小接口。"""

    def plan_recommendation_routes(
        self,
        result: RecommendationResult,
        travel_mode: str = "walking",
    ) -> RecommendationResult:
        """为推荐结果补充路线事实。"""


class MapDataServiceLike(Protocol):
    """地图数据服务需要提供的最小接口。"""

    def build_from_recommendation_result(self, result: RecommendationResult) -> Any:
        """把推荐结果转换为前端地图资源。"""


class RecommendationIntegrationService:
    """把成员一需求模型串联到成员二推荐、依据、路线和地图数据。"""

    def __init__(
        self,
        recommendation_agent: RecommendationAgentLike | None = None,
        evidence_service: EvidenceServiceLike | None = None,
        route_service: RouteServiceLike | None = None,
        map_data_service: MapDataServiceLike | None = None,
    ) -> None:
        """注入成员二各阶段服务，便于测试替换。"""

        self.recommendation_agent = recommendation_agent or RecommendationAgent()
        self.evidence_service = evidence_service or EvidenceEnrichmentService()
        self.route_service = route_service or RouteService()
        self.map_data_service = map_data_service or MapDataService()

    def recommend_for_request(
        self,
        requirements: TravelRequest,
        original_text: str,
        conversation_context: list[str] | None = None,
        assumptions: list[Assumption] | None = None,
        enrich_evidence: bool = True,
        plan_routes: bool = True,
    ) -> dict[str, Any]:
        """用成员一 TravelRequest 真实调用成员二并返回接口可序列化结果。"""

        context = self._build_context(
            requirements=requirements,
            original_text=original_text,
            conversation_context=conversation_context or [],
            assumptions=assumptions or [],
        )

        result = self.recommendation_agent.recommend(context)
        if enrich_evidence:
            result = self._enrich_evidence_safely(result)
        if plan_routes:
            result = self.route_service.plan_recommendation_routes(result)

        map_resources = self.map_data_service.build_from_recommendation_result(result)
        return {
            "recommendation_context": self._context_to_dict(context),
            "recommendation_result": self._result_to_dict(result),
            "map_resources": map_resources.to_dict(),
            "routes": [route.to_dict() for route in result.routes],
        }

    def _enrich_evidence_safely(
        self,
        result: RecommendationResult,
    ) -> RecommendationResult:
        """RAG 依据补充失败时只记录轨迹，不阻断推荐、路线和地图链路。"""

        try:
            return self.evidence_service.enrich_result(result)
        except Exception as exc:
            return replace(
                result,
                agent_trace=[
                    *result.agent_trace,
                    f"RAG依据补充失败，已跳过依据补充并继续推荐链路：{exc}",
                ],
            )

    def _build_context(
        self,
        requirements: TravelRequest,
        original_text: str,
        conversation_context: list[str],
        assumptions: list[Assumption],
    ) -> RecommendationContext:
        """把成员一需求和对话信息整理成成员二上下文。"""

        return RecommendationContext(
            session_id=requirements.session_id,
            requirements=requirements,
            original_text=original_text,
            conversation_context=[
                text.strip() for text in conversation_context if text.strip()
            ],
            semantic_preferences=self._semantic_preferences_from_request(requirements),
            assumptions=[
                self._assumption_to_text(assumption) for assumption in assumptions
            ],
        )

    @staticmethod
    def _semantic_preferences_from_request(
        requirements: TravelRequest,
    ) -> list[SemanticPreference]:
        """把成员一已结构化的偏好转换为成员二语义偏好。"""

        preferences: list[SemanticPreference] = []
        for interest in requirements.interests:
            preferences.append(
                SemanticPreference(text=interest, scope="attraction")
            )
        for place in requirements.must_visit:
            preferences.append(
                SemanticPreference(text=f"必须考虑{place}", scope="attraction")
            )
        for food in requirements.food_preferences:
            preferences.append(
                SemanticPreference(text=food, scope="restaurant")
            )
        for avoidance in requirements.food_avoidances:
            preferences.append(
                SemanticPreference(text=f"避免{avoidance}", scope="restaurant")
            )
        return preferences

    @staticmethod
    def _assumption_to_text(assumption: Assumption) -> str:
        """把成员一的假设说明保留下来，供成员二生成理由时参考。"""

        return f"{assumption.field}={assumption.value}：{assumption.reason}"

    @staticmethod
    def _context_to_dict(context: RecommendationContext) -> dict[str, Any]:
        """把推荐上下文转换成调试友好的字典。"""

        return {
            "session_id": context.session_id,
            "requirements": context.requirements.model_dump(),
            "original_text": context.original_text,
            "conversation_context": list(context.conversation_context),
            "explicit_hard_constraints": [
                asdict(item) for item in context.explicit_hard_constraints
            ],
            "semantic_preferences": [
                asdict(item) for item in context.semantic_preferences
            ],
            "assumptions": list(context.assumptions),
            "unresolved_fields": list(context.unresolved_fields),
        }

    @staticmethod
    def _result_to_dict(result: RecommendationResult) -> dict[str, Any]:
        """把成员二推荐结果转换为 ChatResponse 可直接返回的字典。"""

        return {
            "policy_summary": result.policy_summary,
            "attractions": [place.to_dict() for place in result.attractions],
            "hotels": [place.to_dict() for place in result.hotels],
            "restaurants": [place.to_dict() for place in result.restaurants],
            "routes": [route.to_dict() for route in result.routes],
            "evidence": [asdict(evidence) for evidence in result.evidence],
            "validation_issues": [
                asdict(issue) for issue in result.validation_issues
            ],
            "need_follow_up": result.need_follow_up,
            "follow_up_question": result.follow_up_question,
            "agent_trace": list(result.agent_trace),
        }


__all__ = ["RecommendationIntegrationService"]
