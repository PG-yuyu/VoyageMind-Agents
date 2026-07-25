"""第六步推荐工作流入口。"""

from __future__ import annotations

from backend.app.agents import RecommendationAgent, RecommendationState
from backend.app.schemas import RecommendationContext, RecommendationResult


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
    state = RecommendationState(context=context)
    state.add_trace("接收需求")

    state.policy = recommendation_agent.policy_agent.generate_policy(context)
    state.add_trace("生成推荐策略")
    result = recommendation_agent.recommend(context)
    state.record_candidates(
        attractions=result.attractions,
        hotels=result.hotels,
        restaurants=result.restaurants,
    )
    state.add_trace("查询景点候选")
    state.add_trace("查询酒店候选")
    state.add_trace("查询餐厅候选")
    state.record_result(result)
    state.add_trace("生成推荐结果")

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


ResourceRecommendationWorkflow = run_recommendation_workflow

__all__ = [
    "ResourceRecommendationWorkflow",
    "run_recommendation_workflow",
    "run_recommendation_workflow_with_state",
]
