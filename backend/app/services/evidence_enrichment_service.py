"""推荐结果 RAG 依据补充服务。"""

from __future__ import annotations

from dataclasses import replace

from backend.app.clients import RagClient, RagEvidenceResult
from backend.app.schemas import Evidence, Place, RecommendationResult


MISSING_EVIDENCE_SOURCE = "缺少可靠来源"
MISSING_EVIDENCE_TYPE = "missing_recommendation_evidence"


class EvidenceEnrichmentService:
    """为推荐结果中的地点补充 RAG 推荐依据。"""

    def __init__(
        self,
        rag_client: RagClient | None = None,
        evidence_types: list[str] | None = None,
    ) -> None:
        """注入 RAG 客户端和依据类型。"""

        self.rag_client = rag_client or RagClient()
        self.evidence_types = evidence_types

    def enrich_result(self, result: RecommendationResult) -> RecommendationResult:
        """为推荐结果内的每个重点地点补充至少一条依据说明。"""

        if not isinstance(result, RecommendationResult):
            raise TypeError("RAG 依据补充只能处理 RecommendationResult")

        existing_place_ids = {evidence.place_id for evidence in result.evidence}
        new_evidence = [
            self.build_evidence_for_place(place)
            for place in self._recommended_places(result)
            if place.place_id not in existing_place_ids
        ]
        if not new_evidence:
            return result

        return replace(
            result,
            evidence=[*result.evidence, *new_evidence],
            agent_trace=[
                *result.agent_trace,
                f"补充RAG推荐依据 {len(new_evidence)} 条",
            ],
        )

    def build_evidence_for_place(self, place: Place) -> Evidence:
        """查询并构造单个地点的推荐依据。"""

        if not isinstance(place, Place):
            raise TypeError("推荐依据必须绑定 Place 数据模型")

        rag_result = self.rag_client.get_place_evidence(
            place=place,
            evidence_types=self.evidence_types,
        )
        if rag_result.sufficient and rag_result.sources:
            source = rag_result.sources[0]
            return Evidence(
                place_id=place.place_id,
                summary=rag_result.summary,
                source=source.title,
                page=source.page,
                evidence_type="recommendation_reason",
                sufficient=True,
            )
        return self._missing_evidence(place, rag_result)

    @staticmethod
    def _recommended_places(result: RecommendationResult) -> list[Place]:
        """按成员二输出分类收集推荐地点。"""

        return [
            *result.attractions,
            *result.hotels,
            *result.restaurants,
        ]

    @staticmethod
    def _missing_evidence(place: Place, rag_result: RagEvidenceResult) -> Evidence:
        """构造明确标记为缺少来源的依据说明。"""

        reason = rag_result.missing_reason or "知识库没有返回可追溯来源"
        return Evidence(
            place_id=place.place_id,
            summary=(
                f"{place.name} 当前没有检索到可追溯知识依据；"
                "该说明不能作为来源证明。"
            ),
            source=MISSING_EVIDENCE_SOURCE,
            evidence_type=MISSING_EVIDENCE_TYPE,
            sufficient=False,
            missing_reason=reason,
        )


EvidenceService = EvidenceEnrichmentService

__all__ = [
    "EvidenceEnrichmentService",
    "EvidenceService",
    "MISSING_EVIDENCE_SOURCE",
    "MISSING_EVIDENCE_TYPE",
]
