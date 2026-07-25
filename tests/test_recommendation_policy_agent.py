"""推荐策略 Agent 测试。"""

import pytest

from backend.app.agents import RecommendationPolicyAgent
from backend.app.prompts import RECOMMENDATION_POLICY_PROMPT
from backend.app.schemas import (
    HardConstraint,
    RecommendationContext,
    RecommendationPolicy,
    ResourceFilterPolicy,
    SemanticPreference,
    TravelRequest,
)


def build_context() -> RecommendationContext:
    """构造包含预算、人群、兴趣和偏好的推荐上下文。"""

    requirements = TravelRequest(
        session_id="session_policy_001",
        city="北京",
        days=3,
        people=4,
        total_budget=1200,
        hotel_budget_per_night=260,
        meal_budget_per_person=80,
        interests=["历史文化"],
        food_preferences=["本地风味"],
        food_avoidances=["花生"],
    )
    return RecommendationContext(
        session_id="session_policy_001",
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


def filters_by_type(policy: RecommendationPolicy) -> dict[str, ResourceFilterPolicy]:
    """按资源类型索引过滤策略。"""

    return {item.place_type: item for item in policy.filters}


def test_policy_agent_can_generate_policy_from_context() -> None:
    """合法推荐上下文可以生成推荐策略。"""

    policy = RecommendationPolicyAgent().generate_policy(build_context())

    assert isinstance(policy, RecommendationPolicy)
    assert policy.focus
    assert {item.place_type for item in policy.filters} == {
        "attraction",
        "hotel",
        "restaurant",
    }


def test_policy_reflects_semantic_preferences_and_original_text() -> None:
    """历史文化、毕业旅行、学生等语义能进入策略重点或偏好说明。"""

    policy = RecommendationPolicyAgent().generate_policy(build_context())
    text = " ".join([*policy.focus, *policy.preference_notes])

    assert "历史文化" in text
    assert "毕业旅行" in text
    assert "学生" in text


def test_policy_infers_budget_and_people_direction() -> None:
    """预算字段和人群语义会形成预算倾向和人群偏好。"""

    policy = RecommendationPolicyAgent().generate_policy(build_context())

    assert policy.budget_direction == "预算友好"
    assert "多人同行" in policy.people_direction
    assert "学生" in policy.people_direction
    assert "毕业旅行" in policy.people_direction


def test_policy_keeps_hotel_and_restaurant_directions_separate() -> None:
    """酒店和餐厅偏好会分别体现在对应过滤策略里。"""

    policy = RecommendationPolicyAgent().generate_policy(build_context())
    filters = filters_by_type(policy)

    assert filters["attraction"].area == "东城区"
    assert "历史文化" in filters["attraction"].tags
    assert "博物馆" in filters["attraction"].tags
    assert "交通方便" in filters["hotel"].tags
    assert filters["hotel"].max_price == 260
    assert "本地风味" in filters["restaurant"].tags
    assert filters["restaurant"].max_price == 80


def test_policy_stage_does_not_return_final_places() -> None:
    """策略生成阶段不能越过 Step 6 返回具体推荐资源。"""

    policy = RecommendationPolicyAgent().generate_policy(build_context())

    assert not hasattr(policy, "attractions")
    assert not hasattr(policy, "hotels")
    assert not hasattr(policy, "restaurants")
    assert all(isinstance(item, ResourceFilterPolicy) for item in policy.filters)


def test_policy_model_rejects_invalid_filter_type() -> None:
    """非法资源类型会被策略过滤模型拒绝。"""

    with pytest.raises(ValueError):
        ResourceFilterPolicy(place_type="shopping")


def test_policy_prompt_declares_step_boundary() -> None:
    """策略 Prompt 明确禁止生成最终推荐结果。"""

    assert "不要选择最终景点、酒店、餐厅" in RECOMMENDATION_POLICY_PROMPT
    assert "不要返回具体 Place" in RECOMMENDATION_POLICY_PROMPT
