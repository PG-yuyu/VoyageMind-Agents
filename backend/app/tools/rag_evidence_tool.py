"""RAG 推荐依据查询工具。"""

from __future__ import annotations

from typing import Any

from backend.app.schemas import Evidence, Place, RecommendationResult
from backend.app.services import EvidenceEnrichmentService


def get_place_evidence(
    place: Place | dict[str, Any],
    evidence_types: list[str] | None = None,
    evidence_service: EvidenceEnrichmentService | None = None,
) -> Evidence:
    """为单个推荐地点获取一条 RAG 推荐依据。"""

    place_model = place if isinstance(place, Place) else Place.from_dict(place)
    service = evidence_service or EvidenceEnrichmentService(evidence_types=evidence_types)
    return service.build_evidence_for_place(place_model)


def enrich_recommendation_evidence(
    result: RecommendationResult,
    evidence_types: list[str] | None = None,
    evidence_service: EvidenceEnrichmentService | None = None,
) -> RecommendationResult:
    """为推荐结果补充 RAG 推荐依据。"""

    service = evidence_service or EvidenceEnrichmentService(evidence_types=evidence_types)
    return service.enrich_result(result)


__all__ = [
    "enrich_recommendation_evidence",
    "get_place_evidence",
]
