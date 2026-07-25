"""推荐结果生成 Agent 测试。"""

import pytest

from backend.app.agents import (
    RecommendationAgent,
    RecommendationState,
    ResourceRecommendationAgent,
)
from backend.app.prompts import CANDIDATE_COMPARISON_PROMPT
from backend.app.schemas import (
    HardConstraint,
    RecommendationContext,
    RecommendationResult,
    SemanticPreference,
    TravelRequest,
)
from backend.app.workflows import (
    run_recommendation_workflow,
    run_recommendation_workflow_with_state,
)


def build_context(city: str = "北京") -> RecommendationContext:
    """构造能覆盖第六步主流程的推荐上下文。"""

    requirements = TravelRequest(
        session_id="session_agent_001",
        city=city,
        days=3,
        people=4,
        total_budget=1200,
        hotel_budget_per_night=260,
        meal_budget_per_person=80,
        interests=["历史文化"],
        food_preferences=["本地风味"],
    )
    return RecommendationContext(
        session_id="session_agent_001",
        requirements=requirements,
        original_text="我们四个学生毕业旅行去北京三天，预算不要太高，想看历史文化，也想吃本地风味。",
        semantic_preferences=[
            SemanticPreference(text="想看历史文化和博物馆", scope="attraction"),
            SemanticPreference(text="酒店要交通方便", scope="hotel"),
            SemanticPreference(text="餐厅希望有本地风味", scope="restaurant"),
        ],
        explicit_hard_constraints=[
            HardConstraint(
                field="area",
                operator="equals",
                value="东城区",
                scope="attraction",
                source_text="景点尽量安排在东城区",
            )
        ],
    )


def build_broad_context() -> RecommendationContext:
    """构造没有强过滤条件的推荐上下文，用于验证默认数量规则。"""

    requirements = TravelRequest(
        session_id="session_agent_broad",
        city="北京",
        days=3,
        people=2,
    )
    return RecommendationContext(
        session_id="session_agent_broad",
        requirements=requirements,
        original_text="两个人去北京三天，想看看适合第一次到访的资源。",
    )


def test_recommendation_agent_generates_resource_result() -> None:
    """第六步可以把上下文转换为景点、酒店、餐厅推荐结果。"""

    result = RecommendationAgent().recommend(build_context())

    assert isinstance(result, RecommendationResult)
    assert result.need_follow_up is False
    assert [place.name for place in result.attractions] == ["故宫博物院"]
    assert [place.name for place in result.hotels] == ["西城青年旅舍"]
    assert result.restaurants
    assert all(place.price is not None and place.price <= 80 for place in result.restaurants)


def test_resource_recommendation_agent_alias_is_available() -> None:
    """建议命名 ResourceRecommendationAgent 可以作为主 Agent 别名使用。"""

    result = ResourceRecommendationAgent().recommend(build_context())

    assert isinstance(result, RecommendationResult)
    assert result.attractions


def test_recommendation_agent_uses_default_type_limits() -> None:
    """默认选择景点 3 个、酒店 1 个、餐厅 2 个。"""

    result = RecommendationAgent().recommend(build_broad_context())

    assert len(result.attractions) == 3
    assert len(result.hotels) == 1
    assert len(result.restaurants) == 2


def test_recommendation_agent_keeps_step_six_boundary() -> None:
    """第六步只生成资源推荐，不生成路线、地图和 RAG 证据。"""

    result = RecommendationAgent().recommend(build_context())

    assert result.routes == []
    assert result.evidence == []
    assert "不生成路线、地图或 RAG 证据" in result.agent_trace[-1]


def test_recommendation_workflow_returns_result() -> None:
    """工作流入口可以返回推荐结果。"""

    result = run_recommendation_workflow(build_context())

    assert isinstance(result, RecommendationResult)
    assert result.attractions
    assert "生成推荐结果" in result.agent_trace


def test_recommendation_workflow_state_records_trace() -> None:
    """工作流状态会记录策略、候选资源和执行轨迹。"""

    state = run_recommendation_workflow_with_state(build_context())

    assert isinstance(state, RecommendationState)
    assert state.policy is not None
    assert state.result is not None
    assert state.attraction_candidates
    assert state.hotel_candidates
    assert state.restaurant_candidates
    assert state.trace == [
        "接收需求",
        "生成推荐策略",
        "查询景点候选",
        "查询酒店候选",
        "查询餐厅候选",
        "生成推荐结果",
    ]


def test_recommendation_agent_relaxes_soft_tags_when_needed() -> None:
    """标签没有命中时可以放宽软标签，仍然保留城市和类型条件。"""

    requirements = TravelRequest(
        session_id="session_agent_002",
        city="北京",
        days=2,
        people=2,
        interests=["艺术展览"],
    )
    context = RecommendationContext(
        session_id="session_agent_002",
        requirements=requirements,
        original_text="两个人去北京两天，想看艺术展览。",
    )

    result = RecommendationAgent().recommend(context)

    assert result.attractions
    assert all(place.city == "北京" for place in result.attractions)
    assert all(place.place_type == "attraction" for place in result.attractions)


def test_recommendation_agent_reports_empty_candidates() -> None:
    """样例数据没有匹配城市时返回追问信息和校验问题。"""

    result = RecommendationAgent().recommend(build_context(city="上海"))

    assert result.need_follow_up is True
    assert result.follow_up_question
    assert {issue.field for issue in result.validation_issues} == {
        "attractions",
        "hotels",
        "restaurants",
    }


def test_recommendation_agent_rejects_invalid_context() -> None:
    """主 Agent 只接收 RecommendationContext。"""

    with pytest.raises(TypeError):
        RecommendationAgent().recommend("北京三日游")


def test_candidate_comparison_prompt_declares_boundary() -> None:
    """候选比较 Prompt 明确第六步边界。"""

    assert "不要做每日行程规划" in CANDIDATE_COMPARISON_PROMPT
    assert "不要生成路线、距离、地图标记或交通方案" in CANDIDATE_COMPARISON_PROMPT
    assert "不要调用 RAG" in CANDIDATE_COMPARISON_PROMPT
