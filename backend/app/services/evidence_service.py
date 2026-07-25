"""推荐依据服务兼容入口。"""

from __future__ import annotations

from .evidence_enrichment_service import (
    EvidenceEnrichmentService,
    EvidenceService,
    MISSING_EVIDENCE_SOURCE,
    MISSING_EVIDENCE_TYPE,
)


__all__ = [
    "EvidenceEnrichmentService",
    "EvidenceService",
    "MISSING_EVIDENCE_SOURCE",
    "MISSING_EVIDENCE_TYPE",
]
