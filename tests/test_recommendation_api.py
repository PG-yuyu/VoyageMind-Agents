"""成员二推荐 API 对接测试。"""

from __future__ import annotations

import pytest

from backend.app.api import recommendation_result_to_member3_payload
from backend.app.repositories import PlaceRepository
from backend.app.schemas import Evidence, RecommendationResult, RouteInfo


def _recommendation_result_payload(include_all_types: bool = True) -> dict:
    """构造 HTTP 接口使用的 RecommendationResult 字典。"""

    repository = PlaceRepository()
    attraction = repository.list_attractions()[0]
    hotel = repository.list_hotels()[0]
    restaurant = repository.list_restaurants()[0]
    routes = [
        RouteInfo(
            origin_place_id=hotel.place_id,
            destination_place_id=attraction.place_id,
            distance_meters=1400,
            duration_minutes=20,
            source="manual",
            verified=True,
            polyline=[
                (hotel.coordinate.longitude, hotel.coordinate.latitude),
                (attraction.coordinate.longitude, attraction.coordinate.latitude),
            ],
        ).to_dict()
    ]
    return {
        "policy_summary": "优先选择历史文化资源、交通便利住宿和本地风味餐厅。",
        "attractions": [attraction.to_dict()],
        "hotels": [hotel.to_dict()] if include_all_types else [],
        "restaurants": [restaurant.to_dict()] if include_all_types else [],
        "routes": routes if include_all_types else [],
        "evidence": [
            {
                "place_id": attraction.place_id,
                "summary": f"{attraction.name} 适合历史文化偏好。",
                "source": "测试知识库",
                "page": 1,
                "evidence_type": "recommendation_reason",
                "sufficient": True,
                "missing_reason": None,
            }
        ],
        "validation_issues": [],
        "need_follow_up": False,
        "follow_up_question": None,
        "agent_trace": ["成员二完成资源推荐"],
    }


def _recommendation_result_model() -> RecommendationResult:
    """构造转换函数使用的 RecommendationResult 模型。"""

    payload = _recommendation_result_payload()
    repository = PlaceRepository()
    attraction = repository.list_attractions()[0]
    hotel = repository.list_hotels()[0]
    restaurant = repository.list_restaurants()[0]
    return RecommendationResult(
        policy_summary=payload["policy_summary"],
        attractions=[attraction],
        hotels=[hotel],
        restaurants=[restaurant],
        routes=[RouteInfo.from_dict(payload["routes"][0])],
        evidence=[
            Evidence(
                place_id=attraction.place_id,
                summary=f"{attraction.name} 适合历史文化偏好。",
                source="测试知识库",
                page=1,
            )
        ],
        agent_trace=payload["agent_trace"],
    )


def test_recommendation_result_to_member3_payload_contains_complete_structure() -> None:
    """转换函数能输出成员三需要的完整结构。"""

    payload = recommendation_result_to_member3_payload(_recommendation_result_model())

    assert payload["module"] == "member2_resource_recommendation"
    assert payload["target"] == "member3_itinerary_planning"
    assert payload["ready_for_planning"] is True
    assert payload["resources"]["attractions"]
    assert payload["resources"]["hotels"]
    assert payload["resources"]["restaurants"]
    assert payload["routes"]
    assert payload["step_boundary"]["contains_itinerary_plan"] is False


def test_member3_handoff_http_route_is_registered_and_callable() -> None:
    """主应用已注册成员三对接 HTTP 接口，并且可以直接调用。"""

    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from backend.main import app

    client = TestClient(app)
    response = client.post(
        "/api/v1/member2/recommendations/member3-handoff",
        json=_recommendation_result_payload(),
    )

    assert response.status_code == 200
    data = response.json()
    assert data["ready_for_planning"] is True
    assert data["resources"]["attractions"]
    assert data["routes"]


def test_member3_handoff_marks_incomplete_resources_not_ready() -> None:
    """缺少酒店和餐厅时，接口不能标记为可直接规划。"""

    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from backend.main import app

    client = TestClient(app)
    response = client.post(
        "/api/v1/member2/recommendations/member3-handoff",
        json=_recommendation_result_payload(include_all_types=False),
    )

    assert response.status_code == 200
    data = response.json()
    assert data["ready_for_planning"] is False
    assert "hotels" in data["validation"]["missing_resource_types"]
    assert "restaurants" in data["validation"]["missing_resource_types"]
    assert data["validation"]["status"] == "warning"


def test_main_app_openapi_contains_member3_handoff_path() -> None:
    """OpenAPI 中能看到 Step 11 成员三对接路径。"""

    pytest.importorskip("fastapi")
    from backend.main import app

    paths = set(app.openapi()["paths"])
    assert "/api/v1/member2/recommendations/member3-handoff" in paths

