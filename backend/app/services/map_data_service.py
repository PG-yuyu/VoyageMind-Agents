"""地图展示数据整理服务。"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.app.clients import AmapClient, AmapReverseGeoResult
from backend.app.repositories import PlaceRepository
from backend.app.schemas import Evidence, Place, RecommendationResult


UNVERIFIED_COORDINATE_WARNING = "地点坐标未通过高德地图验证，请前端提示用户确认。"


@dataclass(frozen=True)
class MapResource:
    """前端地图 Marker 和地点卡片需要的资源数据。"""

    place_id: str
    name: str
    place_type: str
    longitude: float
    latitude: float
    address: str
    short_description: str
    recommend_reason: str
    verified: bool
    warning: str | None = None
    source: str = "seed_data"

    def __post_init__(self) -> None:
        """校验地图展示资源的必要字段。"""

        if not self.place_id.strip():
            raise ValueError("地图资源地点编号不能为空")
        if not self.name.strip():
            raise ValueError("地图资源名称不能为空")
        if not self.place_type.strip():
            raise ValueError("地图资源类型不能为空")
        if not self.address.strip():
            raise ValueError("地图资源地址不能为空")
        if not self.short_description.strip():
            raise ValueError("地图资源摘要不能为空")
        if not self.recommend_reason.strip():
            raise ValueError("地图资源推荐理由不能为空")
        if not self.verified and not self.warning:
            raise ValueError("未验证地图资源必须提供提示")

    def to_dict(self) -> dict:
        """转换为前端接口可直接返回的字典。"""

        return {
            "place_id": self.place_id,
            "name": self.name,
            "place_type": self.place_type,
            "longitude": self.longitude,
            "latitude": self.latitude,
            "address": self.address,
            "short_description": self.short_description,
            "recommend_reason": self.recommend_reason,
            "verified": self.verified,
            "warning": self.warning,
            "source": self.source,
        }


@dataclass(frozen=True)
class MapResourceCollection:
    """地图资源集合，包含视野中心和边界。"""

    resources: list[MapResource] = field(default_factory=list)

    def __post_init__(self) -> None:
        """地图资源集合不能为空。"""

        if not self.resources:
            raise ValueError("地图资源集合不能为空")

    @property
    def center(self) -> dict[str, float]:
        """计算地图默认中心点。"""

        return {
            "longitude": round(
                sum(resource.longitude for resource in self.resources)
                / len(self.resources),
                6,
            ),
            "latitude": round(
                sum(resource.latitude for resource in self.resources)
                / len(self.resources),
                6,
            ),
        }

    @property
    def bounds(self) -> dict[str, float]:
        """计算地图展示边界。"""

        longitudes = [resource.longitude for resource in self.resources]
        latitudes = [resource.latitude for resource in self.resources]
        return {
            "min_longitude": min(longitudes),
            "max_longitude": max(longitudes),
            "min_latitude": min(latitudes),
            "max_latitude": max(latitudes),
        }

    def to_dict(self) -> dict:
        """转换为地图接口响应。"""

        return {
            "resources": [resource.to_dict() for resource in self.resources],
            "center": self.center,
            "bounds": self.bounds,
            "warnings": [
                resource.warning
                for resource in self.resources
                if resource.warning is not None
            ],
        }


class MapDataService:
    """把推荐资源转换为前端地图可展示数据。"""

    def __init__(
        self,
        amap_client: AmapClient | None = None,
        place_repository: PlaceRepository | None = None,
    ) -> None:
        """注入高德客户端和地点仓库。"""

        self.amap_client = amap_client or AmapClient()
        self.place_repository = place_repository or PlaceRepository()

    def build_from_recommendation_result(
        self,
        result: RecommendationResult,
    ) -> MapResourceCollection:
        """把推荐结果转换为地图资源集合。"""

        if not isinstance(result, RecommendationResult):
            raise TypeError("地图数据只能从 RecommendationResult 生成")
        evidence_by_place_id = {
            evidence.place_id: evidence for evidence in result.evidence
        }
        places = [
            *result.attractions,
            *result.hotels,
            *result.restaurants,
        ]
        return self.build_from_places(
            places=places,
            evidence_by_place_id=evidence_by_place_id,
            default_reason=result.policy_summary,
        )

    def build_from_place_ids(self, place_ids: list[str]) -> MapResourceCollection:
        """按地点编号生成地图资源集合。"""

        places: list[Place] = []
        for place_id in place_ids:
            place = self.place_repository.get_by_id(place_id)
            if place is None:
                raise ValueError(f"地点不存在：{place_id}")
            places.append(place)
        return self.build_from_places(places)

    def build_from_places(
        self,
        places: list[Place],
        evidence_by_place_id: dict[str, Evidence] | None = None,
        default_reason: str = "推荐资源适合本次旅行需求。",
    ) -> MapResourceCollection:
        """把地点列表转换成地图资源集合。"""

        if not places:
            raise ValueError("地图资源地点列表不能为空")
        evidence_map = evidence_by_place_id or {}
        resources = [
            self._build_resource(
                place=place,
                evidence=evidence_map.get(place.place_id),
                default_reason=default_reason,
            )
            for place in places
        ]
        return MapResourceCollection(resources=resources)

    def _build_resource(
        self,
        place: Place,
        evidence: Evidence | None,
        default_reason: str,
    ) -> MapResource:
        """生成单个地图资源，并尽量用高德验证地址。"""

        if not isinstance(place, Place):
            raise TypeError("地图资源必须使用 Place 数据模型")

        reverse_result = self._reverse_geocode(place)
        verified = reverse_result is not None
        return MapResource(
            place_id=place.place_id,
            name=place.name,
            place_type=place.place_type,
            longitude=place.coordinate.longitude,
            latitude=place.coordinate.latitude,
            address=self._address_for_place(place, reverse_result),
            short_description=self._short_description(place),
            recommend_reason=self._recommend_reason(evidence, default_reason),
            verified=verified,
            warning=None if verified else UNVERIFIED_COORDINATE_WARNING,
            source="amap" if verified else "seed_data",
        )

    def _reverse_geocode(self, place: Place) -> AmapReverseGeoResult | None:
        """用高德逆地理编码验证坐标和地址。"""

        try:
            return self.amap_client.reverse_geocode(place.coordinate)
        except Exception:
            return None

    @staticmethod
    def _address_for_place(
        place: Place,
        reverse_result: AmapReverseGeoResult | None,
    ) -> str:
        """优先使用高德地址，失败时退回样例数据中的城市区域。"""

        if reverse_result and reverse_result.formatted_address.strip():
            return reverse_result.formatted_address.strip()
        return f"{place.city}{place.area}{place.name}"

    @staticmethod
    def _short_description(place: Place) -> str:
        """生成地点卡片摘要。"""

        if place.description.strip():
            return place.description.strip()
        if place.tags:
            return "、".join(place.tags[:3])
        return f"{place.city}{place.area}的{place.name}"

    @staticmethod
    def _recommend_reason(
        evidence: Evidence | None,
        default_reason: str,
    ) -> str:
        """优先使用 RAG 依据作为推荐理由。"""

        if evidence is not None and evidence.summary.strip():
            return evidence.summary.strip()
        return default_reason.strip() or "推荐资源适合本次旅行需求。"


MapResourceService = MapDataService

__all__ = [
    "MapDataService",
    "MapResource",
    "MapResourceCollection",
    "MapResourceService",
    "UNVERIFIED_COORDINATE_WARNING",
]
