"""成员二旅游资源推荐 Agent。"""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from backend.app.prompts import CANDIDATE_COMPARISON_PROMPT
from backend.app.schemas import (
    Place,
    RecommendationContext,
    RecommendationResult,
    ValidationIssue,
)
from backend.app.services import (
    CandidateContextBuilder,
    CandidateResourceContext,
    LLMJsonService,
    ModelDecisionError,
    RecommendationGuard,
)

from .recommendation_policy_agent import RecommendationPolicyAgent
from .recommendation_state import RecommendationState


class RecommendationAgent:
    """由大模型主导选择景点、酒店和餐厅推荐结果。"""

    def __init__(
        self,
        policy_agent: RecommendationPolicyAgent | None = None,
        candidate_builder: CandidateContextBuilder | None = None,
        model_service: LLMJsonService | None = None,
        guard: RecommendationGuard | None = None,
    ) -> None:
        """注入策略 Agent、候选查询服务、大模型服务和硬约束校验器。"""

        self.policy_agent = policy_agent or RecommendationPolicyAgent()
        self.candidate_builder = candidate_builder or CandidateContextBuilder()
        self.model_service = model_service or LLMJsonService()
        self.guard = guard or RecommendationGuard()
        self.last_state: RecommendationState | None = None

    def recommend(self, context: RecommendationContext) -> RecommendationResult:
        """执行第六步推荐流程，软偏好选择由大模型完成。"""

        if not isinstance(context, RecommendationContext):
            raise TypeError("推荐 Agent 只能处理 RecommendationContext")

        state = RecommendationState(context=context)
        state.add_trace("接收需求")

        policy = self.policy_agent.generate_policy(context)
        state.policy = policy
        state.add_trace("生成推荐策略")

        candidates = self.candidate_builder.build(
            policy=policy,
            city=context.requirements.city,
            context=context,
        )
        state.record_candidates(
            attractions=candidates.attractions,
            hotels=candidates.hotels,
            restaurants=candidates.restaurants,
        )
        state.add_trace("查询景点候选")
        state.add_trace("查询酒店候选")
        state.add_trace("查询餐厅候选")

        model_output = self.model_service.request_json(
            CANDIDATE_COMPARISON_PROMPT,
            self._build_model_prompt(context, policy, candidates),
        )
        result = self._result_from_model_output(
            context=context,
            candidates=candidates,
            model_output=model_output,
        )
        state.record_result(result)
        state.add_trace("生成推荐结果")
        self.last_state = state
        return result

    def generate_recommendation(
        self, context: RecommendationContext
    ) -> RecommendationResult:
        """兼容更直观的方法名，内部复用 recommend。"""

        return self.recommend(context)

    def generate_result(self, context: RecommendationContext) -> RecommendationResult:
        """兼容结果生成命名，内部复用 recommend。"""

        return self.recommend(context)

    def run(self, context: RecommendationContext) -> RecommendationResult:
        """兼容工作流调用命名，内部复用 recommend。"""

        return self.recommend(context)

    def _build_model_prompt(
        self,
        context: RecommendationContext,
        policy: Any,
        candidates: CandidateResourceContext,
    ) -> str:
        """构造候选比较输入，要求模型只返回候选 id。"""

        req = context.requirements
        payload = {
            "context": {
                "city": req.city,
                "days": req.days,
                "people": req.people,
                "total_budget": req.total_budget,
                "interests": req.interests,
                "food_preferences": req.food_preferences,
                "preferred_areas": req.preferred_areas,
                "avoid_areas": req.avoid_areas,
                "travel_pace": req.travel_pace,
                "original_text": context.original_text,
                "semantic_preferences": [
                    asdict(p) for p in context.semantic_preferences
                ],
                "hard_constraints": [
                    asdict(c) for c in context.explicit_hard_constraints
                ],
            },
            "recommendation_policy": asdict(policy),
            "candidates": {
                "attractions": [
                    {k: v for k, v in place.to_dict().items()
                     if k in ("place_id", "name", "area", "price", "tags")}
                    for place in candidates.attractions
                ],
                "hotels": [
                    {k: v for k, v in place.to_dict().items()
                     if k in ("place_id", "name", "area", "price", "tags")}
                    for place in candidates.hotels
                ],
                "restaurants": [
                    {k: v for k, v in place.to_dict().items()
                     if k in ("place_id", "name", "area", "price", "tags")}
                    for place in candidates.restaurants
                ],
            },
            "instruction": (
                "请只返回 selected_place_ids，不要返回完整 Place。"
                "如果模型无法在候选中做出合规选择，请设置 need_follow_up。"
            ),
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def _result_from_model_output(
        self,
        context: RecommendationContext,
        candidates: CandidateResourceContext,
        model_output: dict[str, Any],
    ) -> RecommendationResult:
        """把模型选择的候选 id 转换为 RecommendationResult。"""

        self._reject_step_boundary_fields(model_output)
        selected_ids = self._selected_ids(model_output)
        candidate_map = self._candidate_map(candidates)
        candidate_ids = set(candidate_map)

        attractions = self._places_from_ids(
            selected_ids.get("attractions", []),
            candidate_map,
            "attraction",
        )
        hotels = self._places_from_ids(
            selected_ids.get("hotels", []),
            candidate_map,
            "hotel",
        )
        restaurants = self._places_from_ids(
            selected_ids.get("restaurants", []),
            candidate_map,
            "restaurant",
        )

        result = RecommendationResult(
            policy_summary=self._required_str(model_output, "policy_summary"),
            attractions=attractions,
            hotels=hotels,
            restaurants=restaurants,
            routes=[],
            evidence=[],
            validation_issues=self._validation_issues(model_output),
            need_follow_up=self._bool_value(model_output.get("need_follow_up")),
            follow_up_question=self._nullable_str(
                model_output.get("follow_up_question"),
                "follow_up_question",
            ),
            agent_trace=[
                "接收成员一传入的 RecommendationContext",
                "调用大模型生成 RecommendationPolicy",
                "调用 Step 4 候选资源查询服务",
                "调用大模型比较候选资源并选择 place_id",
                *self._str_list(model_output.get("agent_trace", []), "agent_trace"),
                "组装 RecommendationResult，不生成路线、地图或 RAG 证据",
            ],
        )

        hard_issues = self.guard.validate_result(context, result, candidate_ids)
        if hard_issues:
            messages = "；".join(issue.message for issue in hard_issues)
            raise ModelDecisionError(f"大模型推荐结果未通过硬约束校验，请重试：{messages}")
        return result

    def _places_from_ids(
        self,
        place_ids: list[str],
        candidate_map: dict[str, Place],
        expected_type: str,
    ) -> list[Place]:
        """按模型返回的候选 id 取回地点模型。"""

        places: list[Place] = []
        for place_id in place_ids:
            place = candidate_map.get(place_id)
            if place is None:
                raise ModelDecisionError(f"大模型选择了候选池外地点 {place_id}，请重试")
            if place.place_type != expected_type:
                raise ModelDecisionError(f"大模型把 {place_id} 放入了错误分类，请重试")
            places.append(place)
        return places

    def _selected_ids(self, model_output: dict[str, Any]) -> dict[str, list[str]]:
        """读取模型返回的 selected_place_ids。"""

        selected = model_output.get("selected_place_ids")
        if not isinstance(selected, dict):
            raise ModelDecisionError("大模型未返回 selected_place_ids，请重试")
        return {
            "attractions": self._str_list(selected.get("attractions", []), "attractions"),
            "hotels": self._str_list(selected.get("hotels", []), "hotels"),
            "restaurants": self._str_list(
                selected.get("restaurants", []),
                "restaurants",
            ),
        }

    def _validation_issues(
        self,
        model_output: dict[str, Any],
    ) -> list[ValidationIssue]:
        """读取模型声明的非硬约束问题。"""

        issues_data = model_output.get("validation_issues", [])
        if not isinstance(issues_data, list):
            return []  # 非硬约束问题，缺失也不阻断推荐
        issues: list[ValidationIssue] = []
        for item in issues_data:
            if not isinstance(item, dict):
                # LLM 偶尔在数组中混入字符串，跳过即可
                import logging
                logging.getLogger(__name__).warning(
                    "validation_issues 中包含非 dict 元素，已跳过: %s", item
                )
                continue
            try:
                issues.append(
                    ValidationIssue(
                        field=str(item.get("field", "") or ""),
                        message=str(item.get("message", "") or ""),
                        level=str(item.get("level", "warning") or "warning"),
                    )
                )
            except Exception:
                continue
        return issues

    def _reject_step_boundary_fields(self, model_output: dict[str, Any]) -> None:
        """拒绝模型越界输出路线或证据。"""

        if model_output.get("routes"):
            raise ModelDecisionError("Step 6 不允许模型生成路线，请重试")
        if model_output.get("evidence"):
            raise ModelDecisionError("Step 6 不允许模型生成 RAG 证据，请重试")

    @staticmethod
    def _candidate_map(candidates: CandidateResourceContext) -> dict[str, Place]:
        """建立候选地点索引。"""

        return {
            place.place_id: place
            for place in [
                *candidates.attractions,
                *candidates.hotels,
                *candidates.restaurants,
            ]
        }

    @staticmethod
    def _str_list(value: Any, field_name: str) -> list[str]:
        """读取字符串列表字段。"""

        if not isinstance(value, list):
            raise ModelDecisionError(f"大模型字段 {field_name} 必须是字符串列表")
        results: list[str] = []
        for item in value:
            if not isinstance(item, str) or not item.strip():
                raise ModelDecisionError(f"大模型字段 {field_name} 包含非法字符串")
            results.append(item.strip())
        return results

    @staticmethod
    def _required_str(data: dict[str, Any], field_name: str) -> str:
        """读取必填字符串字段。"""

        value = data.get(field_name)
        if not isinstance(value, str) or not value.strip():
            raise ModelDecisionError(f"大模型字段 {field_name} 必须是非空字符串")
        return value.strip()

    @staticmethod
    def _nullable_str(value: Any, field_name: str) -> str | None:
        """读取可空字符串字段。"""

        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            raise ModelDecisionError(f"大模型字段 {field_name} 必须是字符串或 null")
        return value.strip()

    @staticmethod
    def _bool_value(value: Any) -> bool:
        """读取布尔字段。"""

        if not isinstance(value, bool):
            raise ModelDecisionError("大模型字段 need_follow_up 必须是布尔值")
        return value


ResourceRecommendationAgent = RecommendationAgent

__all__ = ["RecommendationAgent", "ResourceRecommendationAgent"]
