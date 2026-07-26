"""
推荐 Agent 客户端
=================

成员三调用成员二的接口（HTTP 或本地函数）。

用于局部重规划时从推荐 Agent 获取替代地点。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


class RecommendationAgentClient:
    """推荐 Agent 客户端。

    支持两种模式：
    1. HTTP 模式：通过 REST API 调用成员二
    2. 本地模式：直接调用传入的函数（用于开发/测试）
    """

    def __init__(
        self,
        base_url: str | None = None,
        local_fetcher: Callable | None = None,
    ):
        """
        Args:
            base_url: 成员二 API 基础 URL（如 http://localhost:8001/api/v1）
            local_fetcher: 本地替代地点获取函数
        """
        self._base_url = base_url
        self._local_fetcher = local_fetcher

    def fetch_alternatives(
        self,
        original_place_id: str,
        constraints: dict[str, Any] | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """获取替代地点。

        Args:
            original_place_id: 需要被替换的原始地点 ID
            constraints: 约束条件（如 indoor=True, max_price=80）
            limit: 返回数量上限

        Returns:
            list[dict]: 替代地点列表
        """
        if self._local_fetcher:
            return self._local_fetcher(
                original_place_id=original_place_id,
                constraints=constraints or {},
                limit=limit,
            )

        if self._base_url:
            return self._http_fetch(original_place_id, constraints, limit)

        logger.warning("RecommendationAgentClient 未配置，返回空列表")
        return []

    def _http_fetch(
        self,
        original_place_id: str,
        constraints: dict[str, Any] | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        """通过 HTTP 获取替代地点。"""
        import urllib.request
        import urllib.error

        url = f"{self._base_url}/recommendations/alternatives"
        data = json.dumps({
            "original_place_id": original_place_id,
            "constraints": constraints or {},
            "limit": limit,
        }).encode("utf-8")

        try:
            req = urllib.request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                return result.get("data", result.get("items", []))
        except urllib.error.HTTPError as exc:
            logger.error("HTTP %d fetching alternatives: %s", exc.code, exc.reason)
            return []
        except Exception as exc:
            logger.error("Failed to fetch alternatives: %s", exc)
            return []

    def recommend_attractions(
        self,
        requirements: dict[str, Any],
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """获取景点推荐（HTTP 模式）。"""
        if not self._base_url:
            return []
        # ... HTTP call similar to above
        return []

    def recommend_restaurants(
        self,
        requirements: dict[str, Any],
        near_place_id: str | None = None,
        meal_type: str | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """获取餐厅推荐。"""
        if not self._base_url:
            return []
        return []
