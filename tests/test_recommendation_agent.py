"""推荐结果生成 Agent 测试。"""

import pytest

from backend.app.agents import (
    RecommendationAgent,
    RecommendationPolicyAgent,
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
from backend.app.services import ModelDecisionError
from backend.app.workflows import (
    run_recommendation_workflow,
    run_recommendation_workflow_with_state,
)


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


def build_context(city: str = "北京") -> RecommendationContext:
    """构造覆盖第六步主流程的推荐上下文。"""

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


def build_context_without_area_constraint() -> RecommendationContext:
    """构造没有明确区域硬约束的推荐上下文。"""

    requirements = TravelRequest(
        session_id="session_agent_no_area",
        city="北京",
        days=3,
        people=4,
        hotel_budget_per_night=260,
        meal_budget_per_person=80,
        interests=["历史文化"],
        food_preferences=["本地风味"],
    )
    return RecommendationContext(
        session_id="session_agent_no_area",
        requirements=requirements,
        original_text="我们四个人去北京三天，交通方便一点，想看历史文化，也想吃本地风味。",
        semantic_preferences=[
            SemanticPreference(text="交通方便一点", scope="overall"),
            SemanticPreference(text="想看历史文化", scope="attraction"),
        ],
    )


def policy_response(include_area: bool = True) -> dict:
    """构造 Step 5 模型策略响应。"""

    return {
        "focus": ["历史文化", "毕业旅行", "本地风味"],
        "filters": [
            {
                "place_type": "attraction",
                "tags": ["历史文化"],
                "area": "东城区" if include_area else None,
                "min_price": None,
                "max_price": None,
            },
            {
                "place_type": "hotel",
                "tags": ["经济型"],
                "area": None,
                "min_price": None,
                "max_price": 260,
            },
            {
                "place_type": "restaurant",
                "tags": ["本地风味"],
                "area": None,
                "min_price": None,
                "max_price": 80,
            },
        ],
        "preference_notes": ["硬约束：景点尽量安排在东城区"],
        "budget_direction": "预算友好",
        "people_direction": ["学生旅行", "多人同行"],
    }


def soft_area_policy_response() -> dict:
    """构造模型把软偏好误写成具体区域的策略。"""

    return {
        "focus": ["交通方便", "历史文化"],
        "filters": [
            {
                "place_type": "attraction",
                "tags": ["历史文化"],
                "area": "海淀区",
                "min_price": None,
                "max_price": None,
            },
            {
                "place_type": "hotel",
                "tags": ["交通便利"],
                "area": "西城区",
                "min_price": None,
                "max_price": 260,
            },
            {
                "place_type": "restaurant",
                "tags": ["本地风味"],
                "area": "西城区",
                "min_price": None,
                "max_price": 80,
            },
        ],
        "preference_notes": ["区域来自软偏好，不应作为候选查询硬过滤。"],
        "budget_direction": "中等预算",
        "people_direction": ["通用"],
    }


def soft_tag_policy_response() -> dict:
    """构造模型返回的非本地标签策略。"""

    return {
        "focus": ["城市休闲观光", "烟火气体验"],
        "filters": [
            {
                "place_type": "attraction",
                "tags": ["热门景点", "适合步行"],
                "area": None,
                "min_price": None,
                "max_price": None,
            },
            {
                "place_type": "hotel",
                "tags": ["高性价比", "交通便利"],
                "area": None,
                "min_price": None,
                "max_price": 260,
            },
            {
                "place_type": "restaurant",
                "tags": ["当地特色", "口碑推荐"],
                "area": None,
                "min_price": None,
                "max_price": 80,
            },
        ],
        "preference_notes": ["模型生成的 tags 是软偏好，不应作为候选查询硬过滤。"],
        "budget_direction": "中等预算，注重性价比",
        "people_direction": ["通用"],
    }


def comparison_response(
    attraction_id: str = "place_001",
    hotel_id: str = "hotel_002",
    restaurant_id: str = "restaurant_001",
) -> dict:
    """构造 Step 6 模型候选选择响应。"""

    return {
        "policy_summary": "模型根据历史文化、预算和本地风味偏好完成资源选择。",
        "selected_place_ids": {
            "attractions": [attraction_id],
            "hotels": [hotel_id],
            "restaurants": [restaurant_id],
        },
        "validation_issues": [],
        "need_follow_up": False,
        "follow_up_question": None,
        "agent_trace": ["大模型完成候选比较"],
    }


def build_agent(
    policy_model: FakeModelService | None = None,
    comparison_model: FakeModelService | None = None,
) -> RecommendationAgent:
    """构造注入假模型的推荐 Agent。"""

    policy_agent = RecommendationPolicyAgent(
        model_service=policy_model or FakeModelService(policy_response())
    )
    return RecommendationAgent(
        policy_agent=policy_agent,
        model_service=comparison_model or FakeModelService(comparison_response()),
    )


def test_recommendation_agent_uses_model_selected_ids() -> None:
    """Step 6 根据大模型返回的候选 id 组装推荐结果。"""

    comparison_model = FakeModelService(comparison_response())
    result = build_agent(comparison_model=comparison_model).recommend(build_context())

    assert isinstance(result, RecommendationResult)
    assert [place.place_id for place in result.attractions] == ["place_001"]
    assert [place.place_id for place in result.hotels] == ["hotel_002"]
    assert [place.place_id for place in result.restaurants] == ["restaurant_001"]
    assert comparison_model.calls
    assert "selected_place_ids" in comparison_model.calls[0][0]
    assert "故宫博物院" in comparison_model.calls[0][1]


def test_resource_recommendation_agent_alias_is_available() -> None:
    """建议命名 ResourceRecommendationAgent 可以作为主 Agent 别名使用。"""

    policy_agent = RecommendationPolicyAgent(
        model_service=FakeModelService(policy_response())
    )
    result = ResourceRecommendationAgent(
        policy_agent=policy_agent,
        model_service=FakeModelService(comparison_response()),
    ).recommend(build_context())

    assert isinstance(result, RecommendationResult)
    assert result.attractions


def test_recommendation_agent_rejects_candidate_outside_pool() -> None:
    """模型选择候选池外地点时，不能本地兜底替换。"""

    agent = build_agent(
        comparison_model=FakeModelService(comparison_response(attraction_id="missing"))
    )

    with pytest.raises(ModelDecisionError):
        agent.recommend(build_context())


def test_recommendation_agent_keeps_candidates_when_model_tags_do_not_match_seed() -> None:
    """模型软标签与样例数据标签不一致时，仍应保留候选池给 Step 6 判断。"""

    comparison_model = FakeModelService(comparison_response())
    agent = build_agent(
        policy_model=FakeModelService(soft_tag_policy_response()),
        comparison_model=comparison_model,
    )

    result = agent.recommend(build_context())

    assert result.attractions
    assert result.hotels
    assert result.restaurants
    assert "故宫博物院" in comparison_model.calls[0][1]


def test_recommendation_agent_ignores_soft_area_filter_without_hard_constraint() -> None:
    """模型把软偏好转成 area 时，没有明确区域硬约束就不能硬过滤候选池。"""

    comparison_model = FakeModelService(comparison_response(attraction_id="place_001"))
    agent = build_agent(
        policy_model=FakeModelService(soft_area_policy_response()),
        comparison_model=comparison_model,
    )

    result = agent.recommend(build_context_without_area_constraint())

    assert [place.place_id for place in result.attractions] == ["place_001"]
    assert "故宫博物院" in comparison_model.calls[0][1]
    assert "颐和园" in comparison_model.calls[0][1]


def test_recommendation_agent_rejects_hard_constraint_violation() -> None:
    """模型选择违反明确区域硬约束的地点时，直接要求重试。"""

    agent = build_agent(
        policy_model=FakeModelService(policy_response(include_area=False)),
        comparison_model=FakeModelService(comparison_response(attraction_id="place_002")),
    )

    with pytest.raises(ModelDecisionError):
        agent.recommend(build_context())


def test_recommendation_agent_does_not_fallback_when_model_fails() -> None:
    """候选比较模型失败时不能回到本地规则选择。"""

    agent = build_agent(
        comparison_model=FakeModelService(ModelDecisionError("模型不可用，请重试"))
    )

    with pytest.raises(ModelDecisionError):
        agent.recommend(build_context())


def test_recommendation_agent_keeps_step_six_boundary() -> None:
    """第六步只生成资源推荐，不生成路线、地图和 RAG 证据。"""

    result = build_agent().recommend(build_context())

    assert result.routes == []
    assert result.evidence == []
    assert "不生成路线、地图或 RAG 证据" in result.agent_trace[-1]


def test_recommendation_workflow_returns_result() -> None:
    """工作流入口可以返回推荐结果。"""

    result = run_recommendation_workflow(build_context(), agent=build_agent())

    assert isinstance(result, RecommendationResult)
    assert result.attractions
    assert "生成推荐结果" in result.agent_trace


def test_recommendation_workflow_state_records_trace() -> None:
    """工作流状态会记录策略、候选资源和执行轨迹。"""

    state = run_recommendation_workflow_with_state(build_context(), agent=build_agent())

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


def test_recommendation_agent_rejects_invalid_context() -> None:
    """主 Agent 只接收 RecommendationContext。"""

    with pytest.raises(TypeError):
        build_agent().recommend("北京三日游")


def test_candidate_comparison_prompt_declares_llm_boundary() -> None:
    """候选比较 Prompt 明确大模型和本地规则边界。"""

    assert "只从 candidates 中选 place_id" in CANDIDATE_COMPARISON_PROMPT
    assert "不做行程规划" in CANDIDATE_COMPARISON_PROMPT
    assert "输出严格 JSON" in CANDIDATE_COMPARISON_PROMPT
