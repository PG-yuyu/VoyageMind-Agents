"""推荐 Agent API 兼容入口。"""

from __future__ import annotations

from .recommendation_api import (
    DEFAULT_SUGGESTED_DURATION_MINUTES,
    MEMBER3_HANDOFF_VERSION,
    build_member3_handoff_payload,
    recommendation_result_from_payload,
    recommendation_result_to_member3_payload,
    router,
)

__all__ = [
    "DEFAULT_SUGGESTED_DURATION_MINUTES",
    "MEMBER3_HANDOFF_VERSION",
    "build_member3_handoff_payload",
    "recommendation_result_from_payload",
    "recommendation_result_to_member3_payload",
    "router",
]
