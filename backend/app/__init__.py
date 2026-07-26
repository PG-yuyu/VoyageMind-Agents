from __future__ import annotations

from dataclasses import dataclass

MODULE_NAME = "travel_resource_recommendation"
MODULE_OWNER = "member2"
STEP_TAG = "member2-step-1-init"


@dataclass(frozen=True)
class RecommendationModuleInfo:
    """推荐模块的轻量级说明信息。"""

    name: str
    owner: str
    tag: str
    responsibility: str


def get_module_info() -> RecommendationModuleInfo:
    """返回第一步验收所需的模块信息。"""

    return RecommendationModuleInfo(
        name=MODULE_NAME,
        owner=MODULE_OWNER,
        tag=STEP_TAG,
        responsibility="将用户需求上下文转换为可验证的旅游资源候选结果。",
    )


__all__ = [
    "MODULE_NAME",
    "MODULE_OWNER",
    "STEP_TAG",
    "RecommendationModuleInfo",
    "get_module_info",
]
