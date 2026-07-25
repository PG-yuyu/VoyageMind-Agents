"""高德地图 Web 服务客户端。"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import urlencode
from urllib.request import urlopen

from backend.app.schemas import Coordinate, Place, RouteInfo


AMAP_API_BASE_URL = "https://restapi.amap.com"
AMAP_KEY_ENV_NAMES = (
    "AMAP_WEB_SERVICE_KEY",
    "AMAP_API_KEY",
    "GAODE_MAP_KEY",
)
AMAP_ROUTE_ENDPOINTS = {
    "walking": "/v3/direction/walking",
    "driving": "/v3/direction/driving",
    "transit": "/v3/direction/transit/integrated",
}


@dataclass(frozen=True)
class AmapGeoResult:
    """高德地理编码结果。"""

    coordinate: Coordinate
    formatted_address: str
    province: str = ""
    city: str = ""
    district: str = ""
    adcode: str = ""
    level: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AmapReverseGeoResult:
    """高德逆地理编码结果。"""

    formatted_address: str
    province: str = ""
    city: str = ""
    district: str = ""
    adcode: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


class AmapClient:
    """封装高德地图 Web 服务 API。"""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = AMAP_API_BASE_URL,
        timeout_seconds: float = 5.0,
        opener: Callable[..., Any] | None = None,
    ) -> None:
        """读取高德 Key，并允许测试注入 HTTP 打开函数。"""

        self.api_key = api_key or self._load_api_key_from_env()
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.opener = opener or urlopen

    @property
    def is_configured(self) -> bool:
        """判断是否已配置高德 Web 服务 Key。"""

        return bool(self.api_key)

    def geocode(self, address: str, city: str | None = None) -> AmapGeoResult | None:
        """调用高德地理编码，把地址或地点名称转换为坐标。"""

        if not self.is_configured:
            return None
        if not address.strip():
            raise ValueError("地理编码地址不能为空")

        payload = self._get_json(
            "/v3/geocode/geo",
            {
                "address": address,
                "city": city,
                "output": "JSON",
            },
        )
        geocodes = payload.get("geocodes", [])
        if not self._is_success(payload) or not geocodes:
            return None

        first = geocodes[0]
        coordinate = self._coordinate_from_location(str(first.get("location", "")))
        if coordinate is None:
            return None
        return AmapGeoResult(
            coordinate=coordinate,
            formatted_address=str(first.get("formatted_address") or address),
            province=self._text_value(first.get("province")),
            city=self._text_value(first.get("city")),
            district=self._text_value(first.get("district")),
            adcode=self._text_value(first.get("adcode")),
            level=self._text_value(first.get("level")),
            raw=first,
        )

    def reverse_geocode(
        self,
        coordinate: Coordinate,
        radius: int = 1000,
    ) -> AmapReverseGeoResult | None:
        """调用高德逆地理编码，把坐标转换为结构化地址。"""

        if not self.is_configured:
            return None
        if not isinstance(coordinate, Coordinate):
            raise TypeError("逆地理编码必须使用 Coordinate 模型")

        payload = self._get_json(
            "/v3/geocode/regeo",
            {
                "location": self._location_text(coordinate),
                "radius": radius,
                "extensions": "base",
                "output": "JSON",
            },
        )
        if not self._is_success(payload):
            return None
        regeocode = payload.get("regeocode")
        if not isinstance(regeocode, dict):
            return None

        address_component = regeocode.get("addressComponent", {})
        return AmapReverseGeoResult(
            formatted_address=str(regeocode.get("formatted_address") or ""),
            province=self._text_value(address_component.get("province")),
            city=self._text_value(address_component.get("city")),
            district=self._text_value(address_component.get("district")),
            adcode=self._text_value(address_component.get("adcode")),
            raw=regeocode,
        )

    def plan_route(
        self,
        origin: Place,
        destination: Place,
        travel_mode: str,
    ) -> RouteInfo | None:
        """调用高德路径规划 API，返回真实道路路线。"""

        if not self.is_configured:
            return None
        if travel_mode not in AMAP_ROUTE_ENDPOINTS:
            raise ValueError("高德路线方式必须是 walking、transit 或 driving")

        payload = self._get_json(
            AMAP_ROUTE_ENDPOINTS[travel_mode],
            {
                "origin": self._location_text(origin.coordinate),
                "destination": self._location_text(destination.coordinate),
                "city": origin.city if travel_mode == "transit" else None,
                "cityd": destination.city if travel_mode == "transit" else None,
                "output": "JSON",
            },
        )
        if not self._is_success(payload):
            return None
        return self._route_info_from_payload(
            payload=payload,
            origin=origin,
            destination=destination,
            travel_mode=travel_mode,
        )

    def _get_json(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        """发送高德 GET 请求并解析 JSON。"""

        if not self.api_key:
            raise RuntimeError("未配置高德 Web 服务 Key")

        query_params = {
            key: value
            for key, value in {
                "key": self.api_key,
                **params,
            }.items()
            if value is not None
        }
        url = f"{self.base_url}{path}?{urlencode(query_params)}"
        with self.opener(url, timeout=self.timeout_seconds) as response:
            body = response.read().decode("utf-8")
        data = json.loads(body)
        if not isinstance(data, dict):
            raise RuntimeError("高德 API 返回格式不是 JSON 对象")
        return data

    def _route_info_from_payload(
        self,
        payload: dict[str, Any],
        origin: Place,
        destination: Place,
        travel_mode: str,
    ) -> RouteInfo | None:
        """从高德路线响应中提取距离、耗时和折线。"""

        route = payload.get("route", {})
        if travel_mode == "transit":
            options = route.get("transits", [])
        else:
            options = route.get("paths", [])
        if not options:
            return None

        first = options[0]
        distance = self._float_value(first.get("distance"))
        duration = self._float_value(first.get("duration"))
        if distance is None or duration is None:
            return None

        return RouteInfo(
            origin_place_id=origin.place_id,
            destination_place_id=destination.place_id,
            distance_meters=distance,
            duration_minutes=round(duration / 60, 2),
            source="amap",
            verified=True,
            polyline=self._polyline_from_route(first, travel_mode),
        )

    @classmethod
    def _polyline_from_route(
        cls,
        route_option: dict[str, Any],
        travel_mode: str,
    ) -> list[tuple[float, float]]:
        """从不同路线类型中提取高德 polyline。"""

        if travel_mode == "transit":
            return cls._polyline_from_transit(route_option)

        points: list[tuple[float, float]] = []
        for step in route_option.get("steps", []) or []:
            points.extend(cls._points_from_polyline(str(step.get("polyline") or "")))
        return points

    @classmethod
    def _polyline_from_transit(
        cls,
        route_option: dict[str, Any],
    ) -> list[tuple[float, float]]:
        """从公交方案的步行段和公交段中提取折线。"""

        points: list[tuple[float, float]] = []
        for segment in route_option.get("segments", []) or []:
            walking = segment.get("walking", {})
            for step in walking.get("steps", []) or []:
                points.extend(cls._points_from_polyline(str(step.get("polyline") or "")))
            bus = segment.get("bus", {})
            for busline in bus.get("buslines", []) or []:
                points.extend(
                    cls._points_from_polyline(str(busline.get("polyline") or ""))
                )
        return points

    @classmethod
    def _points_from_polyline(cls, polyline: str) -> list[tuple[float, float]]:
        """把高德折线字符串转换成经纬度元组。"""

        points: list[tuple[float, float]] = []
        for item in polyline.split(";"):
            coordinate = cls._coordinate_from_location(item)
            if coordinate is not None:
                points.append((coordinate.longitude, coordinate.latitude))
        return points

    @staticmethod
    def _coordinate_from_location(location: str) -> Coordinate | None:
        """解析高德 location 字段，格式为 经度,纬度。"""

        parts = [part.strip() for part in location.split(",")]
        if len(parts) != 2:
            return None
        try:
            return Coordinate(longitude=float(parts[0]), latitude=float(parts[1]))
        except ValueError:
            return None

    @staticmethod
    def _location_text(coordinate: Coordinate) -> str:
        """按高德要求输出 经度,纬度。"""

        return f"{coordinate.longitude:.6f},{coordinate.latitude:.6f}"

    @staticmethod
    def _is_success(payload: dict[str, Any]) -> bool:
        """判断高德响应是否成功。"""

        return str(payload.get("status")) == "1"

    @staticmethod
    def _float_value(value: Any) -> float | None:
        """把高德数字字段转成浮点数。"""

        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _text_value(value: Any) -> str:
        """读取高德文本字段，过滤数组型空值。"""

        return value if isinstance(value, str) else ""

    @staticmethod
    def _load_api_key_from_env() -> str | None:
        """从常见环境变量名读取高德 Web 服务 Key。"""

        for env_name in AMAP_KEY_ENV_NAMES:
            value = os.getenv(env_name)
            if value and value.strip():
                return value.strip()
        return None


__all__ = [
    "AMAP_API_BASE_URL",
    "AMAP_KEY_ENV_NAMES",
    "AMAP_ROUTE_ENDPOINTS",
    "AmapClient",
    "AmapGeoResult",
    "AmapReverseGeoResult",
]
