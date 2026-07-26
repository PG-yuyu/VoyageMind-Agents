"""推荐硬约束校验服务测试。"""

from backend.app.schemas import (
    Coordinate,
    HardConstraint,
    Place,
    RecommendationContext,
    RecommendationResult,
    TravelRequest,
)
from backend.app.services import RecommendationGuard


def build_context() -> RecommendationContext:
    """构造带明确硬约束的推荐上下文。"""

    requirements = TravelRequest(
        session_id="guard_session_001",
        city="北京",
        days=2,
        people=2,
        hotel_budget_per_night=300,
        meal_budget_per_person=80,
        avoid_places=["禁止景点"],
        food_avoidances=["花生"],
    )
    return RecommendationContext(
        session_id="guard_session_001",
        requirements=requirements,
        original_text="两个人去北京两天，酒店每晚不超过300，餐厅人均不超过80。",
        explicit_hard_constraints=[
            HardConstraint(
                field="area",
                operator="equals",
                value="东城区",
                scope="attraction",
                source_text="景点必须在东城区",
            )
        ],
    )


def make_place(
    place_id: str,
    name: str,
    place_type: str,
    area: str,
    price: float,
    city: str = "北京",
    description: str = "",
    tags: list[str] | None = None,
) -> Place:
    """构造测试地点。"""

    return Place(
        place_id=place_id,
        name=name,
        place_type=place_type,
        city=city,
        area=area,
        coordinate=Coordinate(longitude=116.4, latitude=39.9),
        tags=tags or [],
        price=price,
        description=description,
    )


def test_guard_accepts_valid_hard_constraints() -> None:
    """满足城市、类型、价格和区域硬约束时不报错。"""

    attraction = make_place("place_001", "故宫博物院", "attraction", "东城区", 60)
    hotel = make_place("hotel_001", "经济酒店", "hotel", "西城区", 260)
    restaurant = make_place("restaurant_001", "家常菜馆", "restaurant", "东城区", 80)
    result = RecommendationResult(
        policy_summary="模型选择结果",
        attractions=[attraction],
        hotels=[hotel],
        restaurants=[restaurant],
    )

    issues = RecommendationGuard().validate_result(
        build_context(),
        result,
        {"place_001", "hotel_001", "restaurant_001"},
    )

    assert issues == []


def test_guard_reports_hard_constraint_violations() -> None:
    """违反明确硬约束时返回错误级问题。"""

    attraction = make_place("place_002", "颐和园", "attraction", "海淀区", 30)
    hotel = make_place("hotel_002", "高价酒店", "hotel", "东城区", 600)
    restaurant = make_place("restaurant_002", "高价餐厅", "restaurant", "东城区", 120)
    result = RecommendationResult(
        policy_summary="模型选择结果",
        attractions=[attraction],
        hotels=[hotel],
        restaurants=[restaurant],
    )

    issues = RecommendationGuard().validate_result(
        build_context(),
        result,
        {"place_002", "hotel_002", "restaurant_002"},
    )

    assert {issue.field for issue in issues} == {
        "area",
        "hotel_budget_per_night",
        "meal_budget_per_person",
    }
    assert all(issue.level == "error" for issue in issues)


def test_guard_reports_candidate_city_avoidance_food_and_coordinate_issues() -> None:
    """硬约束校验覆盖候选池外、城市、禁止地点、饮食禁忌和坐标缺失。"""

    attraction = make_place(
        "place_outside",
        "禁止景点",
        "attraction",
        "东城区",
        20,
        city="上海",
    )
    object.__setattr__(attraction, "coordinate", None)
    restaurant = make_place(
        "restaurant_003",
        "花生小馆",
        "restaurant",
        "东城区",
        60,
        description="招牌菜含花生酱。",
    )
    result = RecommendationResult(
        policy_summary="模型选择结果",
        attractions=[attraction],
        restaurants=[restaurant],
    )

    issues = RecommendationGuard().validate_result(
        build_context(),
        result,
        {"restaurant_003"},
    )

    fields = {issue.field for issue in issues}
    assert {
        "place_id",
        "coordinate",
        "city",
        "avoid_places",
        "food_avoidances",
    }.issubset(fields)
