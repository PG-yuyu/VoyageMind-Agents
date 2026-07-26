"""路线规划服务测试。"""

import pytest

import backend.app.api.routes_api as routes_api_module
import backend.app.tools.batch_route_tool as batch_route_tool_module
import backend.app.tools.route_plan_tool as route_plan_tool_module
from backend.app.api.routes_api import plan_batch_routes_payload, plan_route_payload
from backend.app.repositories import PlaceRepository
from backend.app.schemas import RecommendationResult, RouteInfo, RouteRequest
from backend.app.services import RouteCacheService, RouteService
from backend.app.tools import plan_route, plan_routes


class FakeAmapClient:
    """测试用高德客户端。"""

    def __init__(self, route: RouteInfo | None = None, should_fail: bool = False) -> None:
        """保存模拟路线或失败状态。"""

        self.route = route
        self.should_fail = should_fail
        self.calls: list[tuple[str, str, str]] = []

    def plan_route(self, origin, destination, travel_mode: str) -> RouteInfo | None:
        """模拟高德路线查询。"""

        self.calls.append((origin.place_id, destination.place_id, travel_mode))
        if self.should_fail:
            raise RuntimeError("高德调用失败")
        return self.route


def test_route_service_plans_straight_line_route_by_place_id() -> None:
    """高德无结果时，路线服务生成未验证的直线估算路线。"""

    service = RouteService(amap_client=FakeAmapClient())
    route = service.plan_route_by_ids("hotel_001", "place_001")

    assert isinstance(route, RouteInfo)
    assert route.origin_place_id == "hotel_001"
    assert route.destination_place_id == "place_001"
    assert route.distance_meters > 0
    assert route.duration_minutes > 0
    assert route.source == "straight_line_estimation"
    assert route.verified is False
    assert route.warning == "路线未经真实道路验证，仅基于经纬度直线距离估算。"
    assert len(route.polyline) == 2


def test_route_service_uses_amap_route_when_available() -> None:
    """高德客户端返回路线时，服务优先使用真实路线结果。"""

    amap_route = RouteInfo(
        origin_place_id="hotel_001",
        destination_place_id="place_001",
        distance_meters=1200,
        duration_minutes=15,
        source="amap",
        verified=True,
        polyline=[(116.405, 39.914), (116.397, 39.916)],
    )
    fake_client = FakeAmapClient(route=amap_route)
    route = RouteService(amap_client=fake_client).plan_route_by_ids(
        "hotel_001",
        "place_001",
        "walking",
    )

    assert route is amap_route
    assert fake_client.calls == [("hotel_001", "place_001", "walking")]


def test_route_service_falls_back_when_amap_fails() -> None:
    """高德异常时，服务回退到带 warning 的直线估算。"""

    route = RouteService(amap_client=FakeAmapClient(should_fail=True)).plan_route_by_ids(
        "hotel_001",
        "place_001",
    )

    assert route.source == "straight_line_estimation"
    assert route.verified is False
    assert route.warning


def test_route_service_uses_travel_mode_speed() -> None:
    """公共交通估算耗时应短于步行估算耗时。"""

    service = RouteService(amap_client=FakeAmapClient())
    walking = service.plan_route_by_ids("hotel_001", "place_001", "walking")
    transit = service.plan_route_by_ids("hotel_001", "place_001", "transit")

    assert transit.duration_minutes < walking.duration_minutes


def test_route_service_caches_route_result() -> None:
    """重复查询同一路线会命中缓存。"""

    cache = RouteCacheService()
    fake_client = FakeAmapClient(should_fail=True)
    service = RouteService(cache_service=cache, amap_client=fake_client)
    request = RouteRequest(
        origin_place_id="hotel_001",
        destination_place_id="place_001",
    )

    first = service.plan_route(request)
    second = service.plan_route(request)

    assert first is second
    assert cache.size() == 1
    assert len(fake_client.calls) == 1


def test_route_service_plans_batch_routes() -> None:
    """路线服务可以批量生成路线事实。"""

    routes = RouteService(amap_client=FakeAmapClient()).plan_batch(
        [
            RouteRequest(
                origin_place_id="hotel_001",
                destination_place_id="place_001",
            ),
            RouteRequest(
                origin_place_id="hotel_001",
                destination_place_id="restaurant_001",
            ),
        ]
    )

    assert len(routes) == 2
    assert all(route.distance_meters > 0 for route in routes)


def test_route_service_enriches_recommendation_result_without_itinerary() -> None:
    """路线服务只补充路线事实，不生成每日行程。"""

    repository = PlaceRepository()
    hotel = repository.get_by_id("hotel_001")
    attraction = repository.get_by_id("place_001")
    restaurant = repository.get_by_id("restaurant_001")
    assert hotel is not None
    assert attraction is not None
    assert restaurant is not None
    result = RecommendationResult(
        policy_summary="模型已选择候选资源。",
        attractions=[attraction],
        hotels=[hotel],
        restaurants=[restaurant],
        agent_trace=["模型推荐完成"],
    )

    enriched = RouteService(amap_client=FakeAmapClient()).plan_recommendation_routes(result)

    assert isinstance(enriched, RecommendationResult)
    assert len(enriched.routes) == 2
    assert enriched.evidence == []
    assert "不生成每日行程" in enriched.agent_trace[-1]
    assert not hasattr(enriched, "itinerary")


def test_route_service_rejects_invalid_input() -> None:
    """不存在的地点和不支持的出行方式会被拒绝。"""

    service = RouteService()

    with pytest.raises(ValueError):
        service.plan_route_by_ids("hotel_001", "missing_place")

    with pytest.raises(ValueError):
        service.plan_route_by_ids("hotel_001", "place_001", "flying")


def test_route_tools_and_payload_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    """工具函数和 API payload 辅助函数可以复用路线服务。"""

    monkeypatch.setattr(
        route_plan_tool_module,
        "RouteService",
        lambda: RouteService(amap_client=FakeAmapClient()),
    )
    monkeypatch.setattr(
        batch_route_tool_module,
        "RouteService",
        lambda: RouteService(amap_client=FakeAmapClient()),
    )
    monkeypatch.setattr(
        routes_api_module,
        "route_service",
        RouteService(amap_client=FakeAmapClient()),
    )

    single_route = plan_route("hotel_001", "place_001")
    batch_routes = plan_routes(
        [
            {
                "origin_place_id": "hotel_001",
                "destination_place_id": "place_001",
                "travel_mode": "walking",
            }
        ]
    )
    single_payload = plan_route_payload(
        {
            "origin_place_id": "hotel_001",
            "destination_place_id": "place_001",
            "travel_mode": "walking",
        }
    )
    batch_payload = plan_batch_routes_payload(
        {
            "routes": [
                {
                    "origin_place_id": "hotel_001",
                    "destination_place_id": "place_001",
                    "travel_mode": "walking",
                }
            ]
        }
    )

    assert single_route.origin_place_id == "hotel_001"
    assert len(batch_routes) == 1
    assert single_payload["source"] == "straight_line_estimation"
    assert len(batch_payload["routes"]) == 1
