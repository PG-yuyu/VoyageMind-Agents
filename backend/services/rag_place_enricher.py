"""
RAG 地点数据实时补全服务
========================

从 LangChain_RAG/docs/tianjin/ 的 txt 文档中解析结构化字段，
在行程构建时实时补全 Place 数据中的价格等信息。

实现"方案 B"：不依赖 data/*.json 的同步步骤，
RAG 文档作为地点数据的唯一真实来源。

用法:
    from backend.services.rag_place_enricher import rag_index

    # 补全单个地点
    place = {"place_id": "tj_place_001", "price": None, ...}
    rag_index.enrich(place)  # price → 0.0 (免费)

    # 批量补全
    places = [...]
    rag_index.enrich_batch(places)
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── 路径常量 ──────────────────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_RAG_DIR = _PROJECT_ROOT / "LangChain_RAG" / "docs" / "tianjin"

# RAG 子目录 → place_type 映射
_SUBDIR_MAP = {
    "attractions": "attraction",
    "restaurants": "restaurant",
    "hotels": "hotel",
}


# ── 字段解析器 ────────────────────────────────────────────────────────


def _parse_price(raw: str) -> float | None:
    """从 RAG 文档的「参考价格」文本中提取数值。

    "免费" → 0, "76元/人" → 76, "1203元/间夜起" → 1203
    """
    if not raw or not raw.strip():
        return None
    text = raw.strip()
    if "免费" in text:
        return 0.0
    m = re.search(r"(\d+)", text)
    return float(m.group(1)) if m else None


def _parse_coordinate(raw: str) -> dict[str, float] | None:
    """解析坐标: "117.211801, 39.085050" → {longitude, latitude}"""
    if not raw or not raw.strip():
        return None
    parts = raw.strip().split(",")
    if len(parts) == 2:
        try:
            lng, lat = float(parts[0].strip()), float(parts[1].strip())
            if -180 <= lng <= 180 and -90 <= lat <= 90:
                return {"longitude": lng, "latitude": lat}
        except (ValueError, TypeError):
            pass
    return None


def _parse_tags(raw: str) -> list[str]:
    """解析逗号/顿号分隔的标签: "博物馆、历史展览、室内展览" → [...]"""
    if not raw or not raw.strip():
        return []
    # 分割符: 中文顿号、逗号、英文逗号
    tags = re.split(r"[、,，]", raw.strip())
    return [t.strip() for t in tags if t.strip()]


# ── RAG 文档解析 ──────────────────────────────────────────────────────


def _parse_rag_document(content: str) -> dict[str, Any] | None:
    """解析单个 RAG txt 文档的结构化字段。

    Returns:
        dict 包含 place_id, place_type, price, open_time, area, tags 等
        解析失败返回 None
    """
    # ── 提取「地点编号」作为主键 ──────────────────────────────────
    m_id = re.search(r"地点编号[：:]\s*(\S+)", content)
    if not m_id:
        return None
    place_id = m_id.group(1).strip()

    result: dict[str, Any] = {"place_id": place_id}

    # ── 逐字段提取 ──────────────────────────────────────────────
    field_patterns = {
        "price": (r"参考价格[：:]\s*(.+)$", _parse_price),
        "open_time": (r"开放/营业时间[：:]\s*(.+)$", lambda v: v.strip() if v else None),
        "area": (r"行政区[：:]\s*(\S+)", lambda v: v.strip() if v else None),
        "city": (r"城市[：:]\s*(\S+)", lambda v: v.strip() if v else None),
        "tags": (r"关键词标签[：:]\s*(.+)$", _parse_tags),
        "suitable_for": (r"适合人群[：:]\s*(.+)$", _parse_tags),
        "coordinate": (r"坐标[：:]\s*(.+)$", _parse_coordinate),
    }

    for field, (pattern, parser) in field_patterns.items():
        m = re.search(pattern, content, re.MULTILINE)
        if m:
            parsed = parser(m.group(1))
            if parsed is not None and parsed != "" and parsed != []:
                result[field] = parsed

    # ── 自然语言介绍（#自然语言介绍 之后到下一个 # 标题之前） ──
    m_desc = re.search(r"#自然语言介绍\s*\n+(.+?)(?=\n#|\Z)", content, re.DOTALL)
    if m_desc:
        desc = m_desc.group(1).strip()
        # 过滤掉以"从行程规划角度"开头的第二段（那是给推荐 Agent 用的）
        lines = desc.split("\n")
        intro_lines = []
        for line in lines:
            if line.startswith("从行程规划角度") or line.startswith("用于前端地图"):
                break
            intro_lines.append(line)
        result["description"] = "\n".join(intro_lines).strip()

    # ── 地点类型 ────────────────────────────────────────────────
    m_type = re.search(r"地点类型[：:].*?（(\w+)）", content)
    if not m_type:
        m_type = re.search(r"地点类型[：:]\s*(\S+)", content)
    if m_type:
        raw_type = m_type.group(1).strip()
        # 规范化: "attraction" | "restaurant" | "hotel"
        type_map = {"景点": "attraction", "attraction": "attraction",
                     "餐厅": "restaurant", "restaurant": "restaurant",
                     "酒店": "hotel", "hotel": "hotel"}
        result["place_type"] = type_map.get(raw_type, raw_type)

    return result


# ── 索引构建 ──────────────────────────────────────────────────────────


def _build_rag_index(rag_dir: Path) -> dict[str, dict[str, Any]]:
    """遍历 RAG 文档目录，构建 place_id → 结构化字段的索引。

    在模块 import 时执行一次，结果缓存在内存中。
    """
    index: dict[str, dict[str, Any]] = {}
    file_count = 0
    fail_count = 0

    if not rag_dir.is_dir():
        logger.warning("RAG 文档目录不存在: %s", rag_dir)
        return index

    for subdir in _SUBDIR_MAP:
        d = rag_dir / subdir
        if not d.is_dir():
            continue
        for fname in os.listdir(d):
            if not fname.endswith(".txt"):
                continue
            try:
                content = (d / fname).read_text(encoding="utf-8")
                parsed = _parse_rag_document(content)
                if parsed and parsed.get("place_id"):
                    index[parsed["place_id"]] = parsed
                    file_count += 1
                else:
                    fail_count += 1
            except Exception:
                fail_count += 1

    logger.info(
        "RAG 地点索引构建完成: %d 个地点, %d 个失败 (目录: %s)",
        file_count, fail_count, rag_dir,
    )
    return index


# ── 公共接口 ──────────────────────────────────────────────────────────


class RAGPlaceIndex:
    """RAG 文档地点数据内存索引。

    提供 O(1) 的 place_id 查询，用于实时补全 Place 数据。
    """

    def __init__(self, rag_dir: Path | None = None):
        self._rag_dir = rag_dir or _RAG_DIR
        self._index: dict[str, dict[str, Any]] = {}
        self._built = False

    @property
    def index(self) -> dict[str, dict[str, Any]]:
        """懒加载：首次访问时构建索引。"""
        if not self._built:
            self._index = _build_rag_index(self._rag_dir)
            self._built = True
        return self._index

    def reload(self) -> int:
        """强制重新加载索引（用于 RAG 文档更新后）。"""
        self._index = _build_rag_index(self._rag_dir)
        self._built = True
        return len(self._index)

    def get(self, place_id: str) -> dict[str, Any] | None:
        """获取指定地点的 RAG 数据。"""
        return self.index.get(place_id)

    def enrich(self, place: dict[str, Any]) -> dict[str, Any]:
        """用 RAG 数据补全单个 Place 字典（原地修改）。

        补全策略：
        - price: 仅当原值为 None 或 0 时用 RAG 值覆盖
        - open_time: 仅当原值为 None 或空时用 RAG 值覆盖
        - 其他字段同理

        Returns:
            修改后的 place 字典（与入参同一对象）
        """
        pid = place.get("place_id", "")
        rag_data = self.index.get(pid)
        if not rag_data:
            return place

        # ── 价格补全 ──────────────────────────────────────────────
        if "price" in rag_data:
            old_price = place.get("price")
            if old_price is None or old_price == 0:
                place["price"] = rag_data["price"]

        # ── 开放时间补全 ──────────────────────────────────────────
        if "open_time" in rag_data:
            old_open = place.get("open_time")
            if not old_open:
                place["open_time"] = rag_data["open_time"]

        # ── 行政区补全 ────────────────────────────────────────────
        if "area" in rag_data:
            old_area = place.get("area")
            if not old_area:
                place["area"] = rag_data["area"]

        # ── 标签补全 ─────────────────────────────────────────────
        if "tags" in rag_data:
            old_tags = place.get("tags") or []
            if not old_tags:
                place["tags"] = rag_data["tags"]

        # ── 自然语言介绍（存在独立字段，不污染 description） ──
        if "description" in rag_data and rag_data["description"]:
            rag_desc = rag_data["description"]
            old_desc = place.get("rag_description") or ""
            if len(rag_desc) > len(old_desc):
                place["rag_description"] = rag_desc

        return place

    def enrich_batch(self, places: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """批量补全 Place 字典列表。

        Returns:
            修改后的 places 列表（原地修改，与入参同一对象）
        """
        for p in places:
            self.enrich(p)
        return places

    def get_price(self, place_id: str) -> float | None:
        """快捷方法：仅获取价格。"""
        rag_data = self.index.get(place_id)
        if rag_data and "price" in rag_data:
            return rag_data["price"]
        return None

    def __len__(self) -> int:
        return len(self.index)

    def __contains__(self, place_id: str) -> bool:
        return place_id in self.index


# ── 全局单例 ──────────────────────────────────────────────────────────

rag_index = RAGPlaceIndex()
