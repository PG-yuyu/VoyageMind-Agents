"""成员二推荐工作流入口。"""

from __future__ import annotations

from backend.app.agents import RecommendationAgent, RecommendationState
from backend.app.schemas import RecommendationContext, RecommendationResult
from backend.app.services import EvidenceEnrichmentService


def run_recommendation_workflow(
    context: RecommendationContext,
    agent: RecommendationAgent | None = None,
) -> RecommendationResult:
    """运行 MVP 推荐工作流，返回推荐结果。"""

    state = run_recommendation_workflow_with_state(context=context, agent=agent)
    if state.result is None:
        raise RuntimeError("推荐工作流未生成结果")
    return state.result


def run_recommendation_workflow_with_state(
    context: RecommendationContext,
    agent: RecommendationAgent | None = None,
) -> RecommendationState:
    """运行推荐工作流，并返回包含 trace 的执行状态。"""

    if not isinstance(context, RecommendationContext):
        raise TypeError("推荐工作流只能处理 RecommendationContext")

    recommendation_agent = agent or RecommendationAgent()
    result = recommendation_agent.recommend(context)
    state = recommendation_agent.last_state
    if state is None:
        raise RuntimeError("推荐 Agent 未记录执行状态")

    merged_trace = [*state.trace, *result.agent_trace]
    state.result = RecommendationResult(
        policy_summary=result.policy_summary,
        attractions=result.attractions,
        hotels=result.hotels,
        restaurants=result.restaurants,
        routes=result.routes,
        evidence=result.evidence,
        validation_issues=result.validation_issues,
        need_follow_up=result.need_follow_up,
        follow_up_question=result.follow_up_question,
        agent_trace=merged_trace,
    )
    return state


def run_recommendation_with_evidence_workflow(
    context: RecommendationContext,
    agent: RecommendationAgent | None = None,
    evidence_service: EvidenceEnrichmentService | None = None,
) -> RecommendationResult:
    """运行推荐流程，并在第八步补充 RAG 推荐依据。"""

    result = run_recommendation_workflow(context=context, agent=agent)
    service = evidence_service or EvidenceEnrichmentService()
    return service.enrich_result(result)


ResourceRecommendationWorkflow = run_recommendation_workflow

__all__ = [
    "ResourceRecommendationWorkflow",
    "run_recommendation_workflow",
    "run_recommendation_with_evidence_workflow",
    "run_recommendation_workflow_with_state",
]
