"""地图资源 API 入口。"""

from __future__ import annotations

from backend.app.schemas import Evidence, Place, RecommendationResult
from backend.app.services import MapDataService

try:
    from fastapi import APIRouter
except ModuleNotFoundError:
    APIRouter = None


map_data_service = MapDataService()
router = (
    APIRouter(prefix="/api/v1/member2/map", tags=["member2-map"])
    if APIRouter
    else None
)


def build_map_resources_by_place_ids_payload(payload: dict) -> dict:
    """按地点编号生成地图资源响应。"""

    place_ids = payload.get("place_ids", [])
    if not isinstance(place_ids, list):
        raise ValueError("place_ids 必须是列表")
    return map_data_service.build_from_place_ids(
        [str(place_id) for place_id in place_ids]
    ).to_dict()


def recommendation_result_to_map_payload(
    result: RecommendationResult,
    service: MapDataService | None = None,
) -> dict:
    """把推荐结果转换为地图资源响应。"""

    map_service = service or map_data_service
    return map_service.build_from_recommendation_result(result).to_dict()


def build_map_resources_from_result_payload(payload: dict) -> dict:
    """从字典形式的推荐结果生成地图资源响应。"""

    result = RecommendationResult(
        policy_summary=str(payload["policy_summary"]),
        attractions=[
            Place.from_dict(item) for item in payload.get("attractions", [])
        ],
        hotels=[Place.from_dict(item) for item in payload.get("hotels", [])],
        restaurants=[
            Place.from_dict(item) for item in payload.get("restaurants", [])
        ],
        evidence=[
            Evidence(
                place_id=str(item["place_id"]),
                summary=str(item["summary"]),
                source=str(item["source"]),
                page=item.get("page"),
                evidence_type=str(
                    item.get("evidence_type", "recommendation_reason")
                ),
                sufficient=bool(item.get("sufficient", True)),
                missing_reason=item.get("missing_reason"),
            )
            for item in payload.get("evidence", [])
        ],
    )
    return recommendation_result_to_map_payload(result)


if router is not None:

    @router.post("/resources/by-place-ids")
    def build_map_resources_by_place_ids_api(payload: dict) -> dict:
        """按地点编号返回地图 Marker 数据。"""

        return build_map_resources_by_place_ids_payload(payload)

    @router.post("/resources/from-recommendation")
    def build_map_resources_from_result_api(payload: dict) -> dict:
        """按推荐结果返回地图 Marker 数据。"""

        return build_map_resources_from_result_payload(payload)


__all__ = [
    "build_map_resources_by_place_ids_payload",
    "build_map_resources_from_result_payload",
    "recommendation_result_to_map_payload",
    "router",
]
