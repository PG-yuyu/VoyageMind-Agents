"""成员二推荐结果对接成员三的 API。"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from backend.app.schemas import (
    Evidence,
    Place,
    RecommendationResult,
    RouteInfo,
    ValidationIssue,
)

try:
    from fastapi import APIRouter
except ModuleNotFoundError:
    APIRouter = None


DEFAULT_SUGGESTED_DURATION_MINUTES = {
    "attraction": 120,
    "hotel": 30,
    "restaurant": 75,
}
MEMBER3_HANDOFF_VERSION = "member2-step-11-integration"

router = (
    APIRouter(prefix="/api/v1/member2/recommendations", tags=["member2-recommendations"])
    if APIRouter
    else None
)


def recommendation_result_to_member3_payload(
    result: RecommendationResult,
) -> dict[str, Any]:
    """把成员二推荐结果转换成成员三可直接使用的规划输入。"""

    if not isinstance(result, RecommendationResult):
        raise TypeError("成员三对接接口只能处理 RecommendationResult")

    evidence_by_place_id = _group_evidence_by_place_id(result.evidence)
    issues_by_place_id = _group_issues_by_place_id(result.validation_issues)
    all_places = [*result.attractions, *result.hotels, *result.restaurants]
    missing_resource_types = _missing_resource_types(result)
    validation_issues = [asdict(issue) for issue in result.validation_issues]
    handoff_warnings = _handoff_warnings(result, missing_resource_types)

    return {
        "module": "member2_resource_recommendation",
        "target": "member3_itinerary_planning",
        "handoff_version": MEMBER3_HANDOFF_VERSION,
        "ready_for_planning": (
            not result.need_follow_up
            and not _has_error_issue(result.validation_issues)
            and not missing_resource_types
        ),
        "policy": {
            "summary": result.policy_summary,
            "need_follow_up": result.need_follow_up,
            "follow_up_question": result.follow_up_question,
        },
        "resources": {
            "attractions": [
                _place_to_planning_resource(
                    place=place,
                    evidence=evidence_by_place_id.get(place.place_id, []),
                    validation_issues=issues_by_place_id.get(place.place_id, []),
                    default_reason=result.policy_summary,
                )
                for place in result.attractions
            ],
            "hotels": [
                _place_to_planning_resource(
                    place=place,
                    evidence=evidence_by_place_id.get(place.place_id, []),
                    validation_issues=issues_by_place_id.get(place.place_id, []),
                    default_reason=result.policy_summary,
                )
                for place in result.hotels
            ],
            "restaurants": [
                _place_to_planning_resource(
                    place=place,
                    evidence=evidence_by_place_id.get(place.place_id, []),
                    validation_issues=issues_by_place_id.get(place.place_id, []),
                    default_reason=result.policy_summary,
                )
                for place in result.restaurants
            ],
        },
        "resource_counts": {
            "attractions": len(result.attractions),
            "hotels": len(result.hotels),
            "restaurants": len(result.restaurants),
            "total": len(all_places),
        },
        "routes": [route.to_dict() for route in result.routes],
        "evidence": [asdict(evidence) for evidence in result.evidence],
        "validation": {
            "status": _validation_status(result.validation_issues, handoff_warnings),
            "issues": validation_issues,
            "handoff_warnings": handoff_warnings,
            "missing_resource_types": missing_resource_types,
        },
        "agent_trace": list(result.agent_trace),
        "step_boundary": {
            "contains_resource_recommendations": True,
            "contains_routes": bool(result.routes),
            "contains_itinerary_plan": False,
            "note": "成员二只提供资源和事实信息，成员三负责组合每日行程。",
        },
    }


def build_member3_handoff_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """处理字典形式的推荐结果，返回成员三对接载荷。"""

    result = recommendation_result_from_payload(payload)
    return recommendation_result_to_member3_payload(result)


def recommendation_result_from_payload(payload: dict[str, Any]) -> RecommendationResult:
    """从接口字典恢复 RecommendationResult。"""

    if not isinstance(payload, dict):
        raise TypeError("推荐结果载荷必须是字典")

    return RecommendationResult(
        policy_summary=str(payload["policy_summary"]),
        attractions=[Place.from_dict(item) for item in payload.get("attractions", [])],
        hotels=[Place.from_dict(item) for item in payload.get("hotels", [])],
        restaurants=[
            Place.from_dict(item) for item in payload.get("restaurants", [])
        ],
        routes=[
            RouteInfo.from_dict(item) for item in payload.get("routes", [])
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
        validation_issues=[
            ValidationIssue(
                field=str(item["field"]),
                message=str(item["message"]),
                level=str(item.get("level", "error")),
            )
            for item in payload.get("validation_issues", [])
        ],
        need_follow_up=bool(payload.get("need_follow_up", False)),
        follow_up_question=payload.get("follow_up_question"),
        agent_trace=[str(item) for item in payload.get("agent_trace", [])],
    )


def _place_to_planning_resource(
    place: Place,
    evidence: list[Evidence],
    validation_issues: list[ValidationIssue],
    default_reason: str,
) -> dict[str, Any]:
    """把地点转换为成员三排程所需的资源事实。"""

    return {
        "place_id": place.place_id,
        "name": place.name,
        "place_type": place.place_type,
        "city": place.city,
        "area": place.area,
        "coordinate": place.coordinate.to_dict(),
        "longitude": place.coordinate.longitude,
        "latitude": place.coordinate.latitude,
        "tags": list(place.tags),
        "price": place.price,
        "open_time": place.open_time,
        "description": place.description,
        "suitable_for": list(place.suitable_for),
        "suggested_visit_duration_minutes": (
            DEFAULT_SUGGESTED_DURATION_MINUTES[place.place_type]
        ),
        "recommend_reason": _recommend_reason(evidence, default_reason),
        "evidence": [asdict(item) for item in evidence],
        "validation_issues": [asdict(item) for item in validation_issues],
    }


def _group_evidence_by_place_id(
    evidence_items: list[Evidence],
) -> dict[str, list[Evidence]]:
    """按地点编号归并推荐依据。"""

    grouped: dict[str, list[Evidence]] = {}
    for evidence in evidence_items:
        grouped.setdefault(evidence.place_id, []).append(evidence)
    return grouped


def _group_issues_by_place_id(
    issues: list[ValidationIssue],
) -> dict[str, list[ValidationIssue]]:
    """按地点编号归并校验问题。"""

    grouped: dict[str, list[ValidationIssue]] = {}
    for issue in issues:
        field = issue.field.strip()
        if field.startswith("place:"):
            place_id = field.split(":", 1)[1]
            grouped.setdefault(place_id, []).append(issue)
    return grouped


def _recommend_reason(evidence: list[Evidence], default_reason: str) -> str:
    """优先使用充分 RAG 依据作为推荐理由。"""

    for item in evidence:
        if item.sufficient and item.summary.strip():
            return item.summary.strip()
    return default_reason


def _missing_resource_types(result: RecommendationResult) -> list[str]:
    """检查成员三排程前必须具备的资源类型。"""

    missing: list[str] = []
    if not result.attractions:
        missing.append("attractions")
    if not result.hotels:
        missing.append("hotels")
    if not result.restaurants:
        missing.append("restaurants")
    return missing


def _handoff_warnings(
    result: RecommendationResult,
    missing_resource_types: list[str],
) -> list[str]:
    """生成不改变推荐结果的对接层提示。"""

    warnings: list[str] = []
    if result.need_follow_up:
        warnings.append("推荐结果仍需要追问，成员三不应直接生成完整行程。")
    if missing_resource_types:
        warnings.append("推荐结果缺少部分资源类型，成员三需要等待补齐后再排程。")
    if not result.routes:
        warnings.append("当前推荐结果未携带路线事实，成员三需要先调用路线接口或等待补充。")
    return warnings


def _has_error_issue(issues: list[ValidationIssue]) -> bool:
    """判断是否存在阻塞成员三排程的错误级问题。"""

    return any(issue.level == "error" for issue in issues)


def _validation_status(
    issues: list[ValidationIssue],
    handoff_warnings: list[str],
) -> str:
    """汇总成员三对接载荷的校验状态。"""

    if _has_error_issue(issues):
        return "failed"
    if handoff_warnings or any(issue.level == "warning" for issue in issues):
        return "warning"
    return "passed"


if router is not None:

    @router.post("/member3-handoff")
    def member3_handoff_api(payload: dict[str, Any]) -> dict[str, Any]:
        """返回成员三可直接消费的推荐资源列表。"""

        return build_member3_handoff_payload(payload)


__all__ = [
    "DEFAULT_SUGGESTED_DURATION_MINUTES",
    "MEMBER3_HANDOFF_VERSION",
    "build_member3_handoff_payload",
    "recommendation_result_from_payload",
    "recommendation_result_to_member3_payload",
    "router",
]
