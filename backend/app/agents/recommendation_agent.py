"""成员二旅游资源推荐 Agent。

这个文件是成员二 Agent 层的主编排器，不直接面向前端 HTTP 请求。
上游通常传入 RecommendationContext，下游得到 RecommendationResult。

主流程可以按下面层级读：
1. RecommendationPolicyAgent：把用户需求解释成推荐策略 RecommendationPolicy。
2. CandidateContextBuilder：根据策略去本地资源库/RAG 补充数据中查候选。
3. LLMJsonService：把候选交给大模型比较，只让模型返回 selected_place_ids。
4. RecommendationGuard：校验模型没有越界、没有违反硬约束、没有选择候选池外资源。
5. RecommendationResult：输出景点、酒店、餐厅三类推荐；路线、地图、证据由后续步骤补。
"""

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
    """成员二推荐主 Agent。

    职责边界：
    - 负责资源推荐，不负责生成每日行程；
    - 可以调用大模型做偏好理解和候选比较；
    - 只能从候选池中选择地点，不能让模型凭空编造 Place；
    - 输出 RecommendationResult，供地图、路线、RAG 证据、下游规划继续使用。
    """

    def __init__(
        self,
        policy_agent: RecommendationPolicyAgent | None = None,
        candidate_builder: CandidateContextBuilder | None = None,
        model_service: LLMJsonService | None = None,
        guard: RecommendationGuard | None = None,
    ) -> None:
        """注入策略 Agent、候选查询服务、大模型服务和硬约束校验器。

        四个依赖分别对应推荐流程的四个关键能力：
        1. policy_agent      负责把自然语言需求转成结构化推荐策略；
        2. candidate_builder 负责从数据源中拉取候选景点、酒店、餐厅；
        3. model_service     负责调用大模型，并要求返回稳定 JSON；
        4. guard             负责兜底校验，防止模型选择不合法结果。
        """

        self.policy_agent = policy_agent or RecommendationPolicyAgent()
        self.candidate_builder = candidate_builder or CandidateContextBuilder()
        self.model_service = model_service or LLMJsonService()
        self.guard = guard or RecommendationGuard()
        self.last_state: RecommendationState | None = None

    def recommend(self, context: RecommendationContext) -> RecommendationResult:
        """执行成员二推荐主流程，软偏好选择由大模型完成。

        输入：
        - RecommendationContext：由上游需求抽取结果、显式硬约束、语义偏好组成。

        输出：
        - RecommendationResult：包含 policy_summary、attractions、hotels、restaurants。
        """

        # 0. 类型入口保护：Agent 层只接收已经结构化的 RecommendationContext。
        #    如果这里传进普通 dict，说明上游接口/集成层还没完成模型转换。
        if not isinstance(context, RecommendationContext):
            raise TypeError("推荐 Agent 只能处理 RecommendationContext")

        # 1. 初始化执行状态。
        #    RecommendationState 不参与推荐决策，只记录中间产物，便于调试和前端 trace 展示。
        state = RecommendationState(context=context)
        state.add_trace("接收需求")

        # 2. 策略生成：让 RecommendationPolicyAgent 调大模型理解用户偏好。
        #    输出的 policy 不含具体地点，只描述“应该如何筛候选”。
        policy = self.policy_agent.generate_policy(context)
        state.policy = policy
        state.add_trace("生成推荐策略")

        # 3. 候选查询：根据 policy 从资源数据中取出三类候选。
        #    注意这里仍没有最终推荐，只是把可选范围准备好。
        candidates = self.candidate_builder.build(
            policy=policy,
            city=context.requirements.city,
            context=context,
        )
        # 3.1 把候选资源存进 state，方便后续排查“大模型是在什么候选池里选的”。
        state.record_candidates(
            attractions=candidates.attractions,
            hotels=candidates.hotels,
            restaurants=candidates.restaurants,
        )
        state.add_trace("查询景点候选")
        state.add_trace("查询酒店候选")
        state.add_trace("查询餐厅候选")

        # 4. 候选比较：把上下文、策略、候选摘要交给大模型。
        #    关键限制：提示词要求模型只返回候选 id，不返回完整地点对象。
        model_output = self.model_service.request_json(
            CANDIDATE_COMPARISON_PROMPT,
            self._build_model_prompt(context, policy, candidates),
        )
        # 5. 结果恢复：把模型选择的 selected_place_ids 映射回真实 Place。
        #    这样可以保证最终输出仍来自候选池和本地/RAG 数据，不是模型虚构文本。
        result = self._result_from_model_output(
            context=context,
            candidates=candidates,
            model_output=model_output,
        )
        # 6. 记录最终结果和 trace，供外层 workflow 或调试页面读取。
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
        """构造候选比较输入，要求模型只返回候选 id。

        这里是“数据喂给大模型”的边界：
        - context 提供用户画像和硬约束；
        - recommendation_policy 提供策略 Agent 的解释结果；
        - candidates 只给简化字段，降低 token，也避免模型修改事实字段。
        """

        req = context.requirements
        # 1. context：告诉模型“用户到底想要什么”。
        #    explicit_hard_constraints 是不能违反的硬条件；
        #    semantic_preferences 是可以用来排序的软偏好。
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
            # 2. recommendation_policy：策略 Agent 给出的筛选方向。
            #    主 Agent 不重新解释策略，只把它交给候选比较提示词。
            "recommendation_policy": asdict(policy),
            # 3. candidates：候选资源摘要。
            #    这里只保留 place_id/name/area/price/tags，模型只负责“选哪个 id”。
            "candidates": {
                "attractions": [
                    {k: v for k, v in place.to_dict().items()
                     if k in ("place_id", "name", "area", "price", "tags", "description")}
                    for place in candidates.attractions
                ],
                "hotels": [
                    {k: v for k, v in place.to_dict().items()
                     if k in ("place_id", "name", "area", "price", "tags", "description")}
                    for place in candidates.hotels
                ],
                "restaurants": [
                    {k: v for k, v in place.to_dict().items()
                     if k in ("place_id", "name", "area", "price", "tags", "description")}
                    for place in candidates.restaurants
                ],
            },
            # 4. instruction：再次声明输出边界。
            #    模型不能直接创造 Place，也不能越权生成路线或证据。
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
        """把模型选择的候选 id 转换为 RecommendationResult。

        这一层是成员二 Agent 的关键安全边界：
        大模型只给选择结果，真正的 Place 对象必须从候选池中取回。
        """

        # 1. 拒绝越界字段。
        #    Step 6 推荐阶段不允许模型直接输出 routes 或 evidence。
        self._reject_step_boundary_fields(model_output)

        # 2. 读取模型选择的三类 id。
        #    selected_ids 仍然只是字符串，不能直接作为最终推荐对象。
        selected_ids = self._selected_ids(model_output)

        # 3. 建立候选索引，用于把 id 映射回真实 Place。
        #    candidate_ids 会交给 guard，用来检查模型是否选了候选池外地点。
        candidate_map = self._candidate_map(candidates)
        candidate_ids = set(candidate_map)

        # 4. 分类型恢复 Place。
        #    每一类都检查 expected_type，防止模型把酒店 id 放进景点列表。
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

        # 5. 组装 RecommendationResult。
        #    注意 routes/evidence 仍为空，因为路线规划和 RAG 证据补充属于后续步骤。
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

        # 6. 硬约束兜底校验。
        #    如果模型选择结果违反预算、区域、候选池等硬条件，直接抛错让上游重试/降级。
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
        """按模型返回的候选 id 取回地点模型。

        这里把“模型输出的字符串 id”变回“后端可信 Place 对象”。
        """

        places: list[Place] = []
        for place_id in place_ids:
            # 1. 必须在候选池中存在，避免模型凭空编造地点。
            place = candidate_map.get(place_id)
            if place is None:
                raise ModelDecisionError(f"大模型选择了候选池外地点 {place_id}，请重试")

            # 2. 必须属于当前资源类型，避免分类错位。
            if place.place_type != expected_type:
                raise ModelDecisionError(f"大模型把 {place_id} 放入了错误分类，请重试")
            places.append(place)
        return places

    def _selected_ids(self, model_output: dict[str, Any]) -> dict[str, list[str]]:
        """读取模型返回的 selected_place_ids。

        期望格式：
        {
            "attractions": ["..."],
            "hotels": ["..."],
            "restaurants": ["..."]
        }
        """

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
        """读取模型声明的非硬约束问题。

        这些问题只作为 warning/error 信息进入结果；
        真正阻断推荐的硬约束仍由 RecommendationGuard 判断。
        """

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
        """拒绝模型越界输出路线或证据。

        成员二主推荐 Agent 的边界是“选择资源”：
        - 路线 routes 由 RouteService / 路线接口负责；
        - RAG 证据 evidence 由 EvidenceEnrichmentService 负责。
        """

        if model_output.get("routes"):
            raise ModelDecisionError("Step 6 不允许模型生成路线，请重试")
        if model_output.get("evidence"):
            raise ModelDecisionError("Step 6 不允许模型生成 RAG 证据，请重试")

    @staticmethod
    def _candidate_map(candidates: CandidateResourceContext) -> dict[str, Place]:
        """建立候选地点索引。

        输入是三类候选列表，输出是 place_id -> Place 的查询表。
        """

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
