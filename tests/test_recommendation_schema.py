import pytest

from backend.app.schemas.place import Coordinate, Place
from backend.app.schemas.recommendation import (
    Evidence,
    ExplicitConstraint,
    HardConstraint,
    KnowledgeSource,
    RecommendationAgentResult,
    RecommendationContext,
    RecommendationResult,
    SemanticPreference,
    TravelRequest,
)
from backend.app.schemas.route import RouteInfo, RouteRequest, RouteResult


def valid_travel_request() -> TravelRequest:
    return TravelRequest(
        session_id="session_001",
        city="北京",
        days=3,
        people=2,
        total_budget=3000,
        interests=["历史文化"],
        transport_modes=["walking", "transit"],
    )


def valid_attraction() -> Place:
    return Place(
        place_id="attr_001",
        name="故宫博物院",
        place_type="attraction",
        city="北京",
        area="东城区",
        coordinate=Coordinate(longitude=116.397026, latitude=39.918058),
        tags=["历史文化", "经典景点"],
        price=60,
        open_time="08:30-17:00",
    )


def valid_hotel() -> Place:
    return Place(
        place_id="hotel_001",
        name="东城区便捷酒店",
        place_type="hotel",
        city="北京",
        area="东城区",
        coordinate=Coordinate(longitude=116.41021, latitude=39.91512),
        tags=["交通方便"],
        price=420,
    )


def valid_restaurant() -> Place:
    return Place(
        place_id="rest_001",
        name="老北京家常菜馆",
        place_type="restaurant",
        city="北京",
        area="东城区",
        coordinate=Coordinate(longitude=116.40563, latitude=39.9142),
        tags=["本地风味"],
        price=80,
    )


def valid_route() -> RouteInfo:
    return RouteInfo(
        origin_place_id="hotel_001",
        destination_place_id="attr_001",
        distance_meters=1800,
        duration_minutes=25,
        source="amap",
        verified=True,
        polyline=[(116.41021, 39.91512), (116.397026, 39.918058)],
    )


def test_can_build_valid_recommendation_context() -> None:
    context = RecommendationContext(
        session_id="session_001",
        requirements=valid_travel_request(),
        original_text="我们两个人去北京玩三天，预算3000元以内，想看历史文化景点。",
        explicit_hard_constraints=[
            HardConstraint(
                field="total_budget",
                operator="less_than_or_equal",
                value=3000,
                scope="overall",
                source_text="预算3000元以内",
            )
        ],
        semantic_preferences=[
            SemanticPreference(text="想看历史文化景点", scope="attraction")
        ],
    )

    assert context.session_id == "session_001"
    assert context.requirements.city == "北京"
    assert context.requirements.interests == ["历史文化"]


def test_empty_session_id_is_rejected() -> None:
    with pytest.raises(ValueError):
        RecommendationContext(
            session_id="",
            requirements=valid_travel_request(),
            original_text="我们两个人去北京玩三天。",
        )


def test_member1_travel_request_can_be_used_directly() -> None:
    member1_request = TravelRequest(
        session_id="session_001",
        city="天津",
        days=2,
        people=2,
        total_budget=1200,
        interests=["近代建筑", "美食"],
        must_visit=["五大道文化旅游区"],
        avoid_places=["过度商业化景点"],
        food_preferences=["天津菜"],
        food_avoidances=["花生"],
        walking_limit_m=6000,
        daily_start_time="10:00",
        daily_end_time="18:00",
        travel_pace="relaxed",
    )

    context = RecommendationContext(
        session_id="session_001",
        requirements=member1_request,
        original_text="两个人去天津两天，想看近代建筑和吃天津菜，步行别超过6000米。",
    )

    assert context.requirements is member1_request
    assert context.requirements.must_visit == ["五大道文化旅游区"]


def test_can_build_valid_recommendation_result() -> None:
    result = RecommendationResult(
        policy_summary="优先推荐北京东城区的历史文化景点和交通方便的酒店。",
        attractions=[valid_attraction()],
        hotels=[valid_hotel()],
        restaurants=[valid_restaurant()],
        routes=[valid_route()],
        evidence=[
            Evidence(
                place_id="attr_001",
                summary="故宫适合历史文化主题旅行。",
                source="北京历史文化景点资料.md",
                page=1,
            )
        ],
        validation_issues=[],
        need_follow_up=False,
        agent_trace=["生成推荐策略", "完成 Schema 校验"],
    )

    assert result.attractions[0].place_type == "attraction"
    assert result.hotels[0].place_type == "hotel"
    assert result.restaurants[0].place_type == "restaurant"


def test_common_schema_compatibility_aliases() -> None:
    route_request = RouteRequest(
        origin_place_id="hotel_001",
        destination_place_id="attr_001",
    )

    assert route_request.travel_mode == "walking"
    assert ExplicitConstraint is HardConstraint
    assert KnowledgeSource is Evidence
    assert RecommendationAgentResult is RecommendationResult
    assert RouteResult is RouteInfo


@pytest.mark.parametrize(
    "payload",
    [
        {"session_id": "session_001", "city": "", "days": 3, "people": 2, "total_budget": 3000},
        {"session_id": "session_001", "city": "北京", "days": 0, "people": 2, "total_budget": 3000},
        {"session_id": "session_001", "city": "北京", "days": 3, "people": 0, "total_budget": 3000},
        {"session_id": "session_001", "city": "北京", "days": 3, "people": 2, "total_budget": -1},
    ],
)
def test_invalid_member1_travel_request_is_rejected_by_context(payload: dict) -> None:
    with pytest.raises(ValueError):
        RecommendationContext(
            session_id="session_001",
            requirements=TravelRequest(**payload),
            original_text="北京三日游。",
        )


def test_context_rejects_session_id_mismatch() -> None:
    with pytest.raises(ValueError):
        RecommendationContext(
            session_id="session_001",
            requirements=TravelRequest(
                session_id="session_002",
                city="北京",
                days=3,
                people=2,
            ),
            original_text="北京三日游。",
        )


@pytest.mark.parametrize(
    "longitude, latitude",
    [(181, 39.9), (116.3, 91)],
)
def test_invalid_coordinate_is_rejected(longitude: float, latitude: float) -> None:
    with pytest.raises(ValueError):
        Coordinate(longitude=longitude, latitude=latitude)


def test_invalid_place_is_rejected() -> None:
    coordinate = Coordinate(longitude=116.397026, latitude=39.918058)

    invalid_places = [
        {"place_id": "", "name": "故宫", "place_type": "attraction", "city": "北京", "area": "东城区", "coordinate": coordinate},
        {"place_id": "attr_001", "name": "", "place_type": "attraction", "city": "北京", "area": "东城区", "coordinate": coordinate},
        {"place_id": "shop_001", "name": "购物中心", "place_type": "shopping", "city": "北京", "area": "朝阳区", "coordinate": coordinate},
        {"place_id": "attr_001", "name": "故宫", "place_type": "attraction", "city": "北京", "area": "东城区", "coordinate": coordinate, "price": -1},
    ]

    for payload in invalid_places:
        with pytest.raises(ValueError):
            Place(**payload)


def test_result_rejects_wrong_place_category() -> None:
    with pytest.raises(ValueError):
        RecommendationResult(
            policy_summary="测试分类错误",
            attractions=[valid_hotel()],
        )


def test_result_requires_follow_up_question() -> None:
    with pytest.raises(ValueError):
        RecommendationResult(
            policy_summary="测试追问字段",
            need_follow_up=True,
            follow_up_question="",
        )


def test_evidence_required_fields_are_rejected() -> None:
    with pytest.raises(TypeError):
        Evidence(summary="故宫适合历史文化旅行", source="资料.md")

    with pytest.raises(TypeError):
        Evidence(place_id="attr_001", summary="故宫适合历史文化旅行")
