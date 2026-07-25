"""地图接口与坐标处理测试。"""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

import pytest

from backend.app.api.map_resource_api import (
    build_map_resources_by_place_ids_payload,
    recommendation_result_to_map_payload,
    router as map_resource_router,
)
from backend.app.clients import AmapClient, AmapReverseGeoResult
from backend.app.repositories import PlaceRepository
from backend.app.schemas import Evidence, RecommendationResult, RouteInfo
from backend.app.services import (
    MapDataService,
    MapResourceCollection,
    UNVERIFIED_COORDINATE_WARNING,
)


class FakeHttpResponse:
    """测试用 HTTP 响应对象。"""

    def __init__(self, payload: dict) -> None:
        """保存 JSON 响应体。"""

        self.payload = payload

    def __enter__(self):
        """支持 with 语法。"""

        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        """退出 with 语法时不需要额外处理。"""

    def read(self) -> bytes:
        """返回 JSON 字节内容。"""

        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")


class FakeOpener:
    """测试用高德 HTTP 打开函数。"""

    def __init__(self, payloads: list[dict]) -> None:
        """保存每次请求对应的响应。"""

        self.payloads = list(payloads)
        self.urls: list[str] = []

    def __call__(self, url: str, timeout: float) -> FakeHttpResponse:
        """记录请求地址，并返回下一条响应。"""

        self.urls.append(url)
        assert timeout > 0
        if not self.payloads:
            raise AssertionError("没有可用的高德测试响应")
        return FakeHttpResponse(self.payloads.pop(0))


class FakeAmapClient:
    """测试用高德客户端。"""

    def __init__(self, address: str | None = "北京市东城区景山前街4号") -> None:
        """保存是否返回高德地址。"""

        self.address = address
        self.calls = []

    def reverse_geocode(self, coordinate):
        """模拟高德逆地理编码。"""

        self.calls.append((coordinate.longitude, coordinate.latitude))
        if self.address is None:
            return None
        return AmapReverseGeoResult(
            formatted_address=self.address,
            city="北京",
            district="东城区",
            adcode="110101",
        )


def build_result() -> RecommendationResult:
    """构造地图测试用推荐结果。"""

    repository = PlaceRepository()
    attraction = repository.get_by_id("place_001")
    hotel = repository.get_by_id("hotel_001")
    restaurant = repository.get_by_id("restaurant_001")
    assert attraction is not None
    assert hotel is not None
    assert restaurant is not None
    return RecommendationResult(
        policy_summary="模型推荐了适合本次旅行的资源。",
        attractions=[attraction],
        hotels=[hotel],
        restaurants=[restaurant],
        evidence=[
            Evidence(
                place_id="place_001",
                summary="故宫适合作为历史文化主题旅行依据。",
                source="北京历史文化资料.pdf",
                page=2,
            )
        ],
    )


def test_amap_client_geocode_and_reverse_geocode_parse_response() -> None:
    """高德客户端可以调用地理编码和逆地理编码接口。"""

    opener = FakeOpener(
        [
            {
                "status": "1",
                "geocodes": [
                    {
                        "formatted_address": "北京市东城区故宫博物院",
                        "location": "116.397026,39.918058",
                        "city": "北京市",
                        "district": "东城区",
                        "adcode": "110101",
                        "level": "兴趣点",
                    }
                ],
            },
            {
                "status": "1",
                "regeocode": {
                    "formatted_address": "北京市东城区景山前街4号",
                    "addressComponent": {
                        "city": "北京市",
                        "district": "东城区",
                        "adcode": "110101",
                    },
                },
            },
        ]
    )
    client = AmapClient(api_key="test-key", opener=opener)

    geo = client.geocode("故宫博物院", city="北京")
    reverse = client.reverse_geocode(geo.coordinate)

    assert geo.formatted_address == "北京市东城区故宫博物院"
    assert geo.coordinate.longitude == 116.397026
    assert reverse.formatted_address == "北京市东城区景山前街4号"
    assert "/v3/geocode/geo" in opener.urls[0]
    assert parse_qs(urlparse(opener.urls[0]).query)["key"] == ["test-key"]
    assert "/v3/geocode/regeo" in opener.urls[1]


def test_amap_client_plan_route_uses_web_service_response() -> None:
    """高德客户端可以把路径规划响应转成 RouteInfo。"""

    opener = FakeOpener(
        [
            {
                "status": "1",
                "route": {
                    "paths": [
                        {
                            "distance": "1200",
                            "duration": "900",
                            "steps": [
                                {
                                    "polyline": (
                                        "116.410210,39.915120;"
                                        "116.397026,39.918058"
                                    )
                                }
                            ],
                        }
                    ]
                },
            }
        ]
    )
    repository = PlaceRepository()
    origin = repository.get_by_id("hotel_001")
    destination = repository.get_by_id("place_001")
    assert origin is not None
    assert destination is not None

    route = AmapClient(api_key="test-key", opener=opener).plan_route(
        origin,
        destination,
        "walking",
    )

    assert isinstance(route, RouteInfo)
    assert route.source == "amap"
    assert route.verified is True
    assert route.distance_meters == 1200
    assert route.duration_minutes == 15
    assert len(route.polyline) == 2
    assert "/v3/direction/walking" in opener.urls[0]


def test_map_data_service_builds_verified_map_resources() -> None:
    """地图服务返回前端需要的 Marker 和卡片字段。"""

    service = MapDataService(amap_client=FakeAmapClient())

    collection = service.build_from_recommendation_result(build_result())
    payload = collection.to_dict()

    assert isinstance(collection, MapResourceCollection)
    assert len(payload["resources"]) == 3
    first = payload["resources"][0]
    assert first["place_id"] == "place_001"
    assert first["name"] == "故宫博物院"
    assert first["place_type"] == "attraction"
    expected_place = PlaceRepository().get_by_id("place_001")
    assert expected_place is not None
    assert first["longitude"] == expected_place.coordinate.longitude
    assert first["latitude"] == expected_place.coordinate.latitude
    assert first["address"] == "北京市东城区景山前街4号"
    assert first["recommend_reason"] == "故宫适合作为历史文化主题旅行依据。"
    assert first["verified"] is True
    assert first["source"] == "amap"
    assert payload["warnings"] == []


def test_map_data_service_marks_unverified_when_amap_missing() -> None:
    """高德未返回地址时，地图资源必须标记未验证并给出提示。"""

    service = MapDataService(amap_client=FakeAmapClient(address=None))

    payload = service.build_from_recommendation_result(build_result()).to_dict()

    assert all(not item["verified"] for item in payload["resources"])
    assert all(item["source"] == "seed_data" for item in payload["resources"])
    assert UNVERIFIED_COORDINATE_WARNING in payload["warnings"]


def test_map_resource_api_payload_helpers() -> None:
    """地图 API 辅助函数可以输出地点编号和推荐结果两类响应。"""

    by_ids_payload = build_map_resources_by_place_ids_payload(
        {"place_ids": ["place_001", "hotel_001"]}
    )
    result_payload = recommendation_result_to_map_payload(
        build_result(),
        service=MapDataService(amap_client=FakeAmapClient()),
    )

    assert len(by_ids_payload["resources"]) == 2
    assert len(result_payload["resources"]) == 3
    assert "center" in result_payload
    assert "bounds" in result_payload


def test_map_resource_router_is_registered_in_main_app() -> None:
    """地图资源路由需要注册到主 FastAPI 应用中。"""

    test_client_module = pytest.importorskip("fastapi.testclient")

    from backend.main import app

    assert map_resource_router is not None
    client = test_client_module.TestClient(app)
    paths = set(client.get("/openapi.json").json()["paths"])
    assert "/api/v1/member2/map/resources/by-place-ids" in paths
    assert "/api/v1/member2/map/resources/from-recommendation" in paths


def test_map_data_service_rejects_empty_or_missing_places() -> None:
    """空地点列表和不存在的地点编号会被明确拒绝。"""

    service = MapDataService(amap_client=FakeAmapClient())

    with pytest.raises(ValueError):
        service.build_from_places([])

    with pytest.raises(ValueError):
        service.build_from_place_ids(["missing_place"])
