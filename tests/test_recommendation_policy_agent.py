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
from backend.app.services import ModelDecisionError


class FakeModelService:
    """测试用大模型服务。"""

    def __init__(self, response: dict | Exception) -> None:
        """保存固定响应。"""

        self.response = response
        self.calls: list[tuple[str, str]] = []

    def request_json(self, system_prompt: str, user_prompt: str) -> dict:
        """记录调用并返回预设 JSON。"""

        self.calls.append((system_prompt, user_prompt))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def build_context(with_price: bool = True) -> RecommendationContext:
    """构造包含硬约束和隐含偏好的推荐上下文。"""

    requirements = TravelRequest(
        session_id="session_policy_001",
        city="北京",
        days=3,
        people=4,
        total_budget=1200,
        hotel_budget_per_night=260 if with_price else None,
        meal_budget_per_person=80 if with_price else None,
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


def model_policy_response(
    hotel_max_price: float | None = 260,
    restaurant_max_price: float | None = 80,
) -> dict:
    """构造模型返回的策略 JSON。"""

    return {
        "focus": ["历史文化", "毕业旅行纪念感", "交通便利"],
        "filters": [
            {
                "place_type": "attraction",
                "tags": ["历史文化", "博物馆"],
                "area": "东城区",
                "min_price": None,
                "max_price": None,
            },
            {
                "place_type": "hotel",
                "tags": ["交通方便", "适合学生"],
                "area": None,
                "min_price": None,
                "max_price": hotel_max_price,
            },
            {
                "place_type": "restaurant",
                "tags": ["本地风味"],
                "area": None,
                "min_price": None,
                "max_price": restaurant_max_price,
            },
        ],
        "preference_notes": [
            "用户是学生毕业旅行，但不能把学生固定换算成价格。",
            "硬约束：景点尽量安排在东城区",
        ],
        "budget_direction": "预算友好",
        "people_direction": ["学生旅行", "多人同行"],
    }


def filters_by_type(policy: RecommendationPolicy) -> dict[str, ResourceFilterPolicy]:
    """按资源类型索引过滤策略。"""

    return {item.place_type: item for item in policy.filters}


def test_policy_agent_uses_model_output() -> None:
    """Step 5 使用大模型输出生成策略，而不是本地规则推断。"""

    fake_model = FakeModelService(model_policy_response())
    policy = RecommendationPolicyAgent(model_service=fake_model).generate_policy(
        build_context()
    )
    filters = filters_by_type(policy)

    assert isinstance(policy, RecommendationPolicy)
    assert policy.focus == ["历史文化", "毕业旅行纪念感", "交通便利"]
    assert filters["attraction"].area == "东城区"
    assert filters["hotel"].max_price == 260
    assert filters["restaurant"].max_price == 80
    assert fake_model.calls
    assert "RecommendationContext" in fake_model.calls[0][0]
    assert "预算不要太高" in fake_model.calls[0][1]


def test_policy_agent_rejects_soft_budget_as_price_filter() -> None:
    """没有明确单项价格上限时，模型不能把软预算偏好写成价格过滤。"""

    fake_model = FakeModelService(
        model_policy_response(hotel_max_price=300, restaurant_max_price=None)
    )

    with pytest.raises(ModelDecisionError):
        RecommendationPolicyAgent(model_service=fake_model).generate_policy(
            build_context(with_price=False)
        )


def test_policy_agent_does_not_fallback_when_model_fails() -> None:
    """大模型失败时不能走本地规则兜底。"""

    fake_model = FakeModelService(ModelDecisionError("模型不可用，请重试"))

    with pytest.raises(ModelDecisionError):
        RecommendationPolicyAgent(model_service=fake_model).generate_policy(
            build_context()
        )


def test_policy_stage_does_not_return_final_places() -> None:
    """策略生成阶段不能越过 Step 6 返回具体推荐资源。"""

    policy = RecommendationPolicyAgent(
        model_service=FakeModelService(model_policy_response())
    ).generate_policy(build_context())

    assert not hasattr(policy, "attractions")
    assert not hasattr(policy, "hotels")
    assert not hasattr(policy, "restaurants")
    assert all(isinstance(item, ResourceFilterPolicy) for item in policy.filters)


def test_policy_model_rejects_invalid_filter_type() -> None:
    """非法资源类型会被策略过滤模型拒绝。"""

    with pytest.raises(ValueError):
        ResourceFilterPolicy(place_type="shopping")


def test_policy_prompt_declares_llm_boundary() -> None:
    """策略 Prompt 明确大模型和本地规则边界。"""

    assert "隐含偏好必须由你结合原文" in RECOMMENDATION_POLICY_PROMPT
    assert "不要使用固定规则" in RECOMMENDATION_POLICY_PROMPT
    assert "不要选择最终景点、酒店、餐厅" in RECOMMENDATION_POLICY_PROMPT
