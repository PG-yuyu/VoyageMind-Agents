"""
调整 Agent — 用户主动修改 + 局部重规划
=========================================

处理用户修改请求（替换景点、更换餐厅、减少步行、改为室内等）。

流程:
  1. 接收 ModificationRequest
  2. 锁定不受影响的行程项
  3. LLM 分析修改影响范围
  4. 如需要替代资源 → 调用 recommendation_agent_client
  5. LLM 局部重规划受影响时段
  6. 工具重新计算路线和费用
  7. 规则检查硬约束
  8. LLM 再次判断软偏好
  9. 保存新版本，生成 TripDiff
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

from backend.prompts.local_replan_prompt import LOCAL_REPLAN_PROMPT
from backend.schemas.modification import ModificationRequest
from backend.schemas.version import TripDiff

from backend.services.budget_service import calculate_budget
from backend.services.version_service import (
    clone_for_modification,
    diff_versions,
    get_itinerary,
    lock_items_except,
    save_version,
    unlock_items,
)
from backend.validators.hard_constraint_validator import (
    enrich_items_with_places,
    validate_hard_constraints,
)

logger = logging.getLogger(__name__)


class AdjustmentAgent:
    """调整 Agent —— 用户主动修改 + 局部重规划。"""

    def __init__(
        self,
        llm_callable: Callable[[str], str],
        alternative_place_fetcher: Callable | None = None,
    ):
        """
        Args:
            llm_callable: LLM 调用函数, 签名 (prompt: str) -> str
            alternative_place_fetcher: 获取替代地点的函数，签名:
                (original_place_id, constraints) -> list[dict]
        """
        self._llm = llm_callable
        self._fetch_alternatives = alternative_place_fetcher

    # ====================================================================
    # 主入口
    # ====================================================================

    def modify(
        self,
        request: ModificationRequest | dict[str, Any],
        requirements: dict[str, Any] | None = None,
        places: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """执行用户修改请求。

        Args:
            request: ModificationRequest 字典或对象
            requirements: TravelRequest 字典
            places: 完整候选地点列表

        Returns:
            dict: {
                "itinerary": Itinerary (新版本),
                "evaluation": HardConstraintEvaluation,
                "diff": TripDiff,
                "budget": BudgetSummary,
                "agent_trace": [...]
            }
        """
        req = _d(request)
        session_id = req.get("session_id", "")
        itinerary_id = req.get("itinerary_id", "")
        base_version = req.get("base_version", 1)
        action = req.get("action", "")
        target_day = req.get("target_day")
        target_item_id = req.get("target_item_id")
        new_constraints = req.get("new_constraints", {})
        original_text = req.get("original_text", "")

        trace: list[dict] = []
        trace.append({
            "step": 1,
            "agent": "adjustment_agent",
            "action": "receive_modification",
            "summary": f"收到修改: {action}",
            "status": "success",
        })

        # ── 1. 获取当前行程 ────────────────────────────────────────
        old_itinerary = get_itinerary(itinerary_id, base_version)
        if old_itinerary is None:
            return {
                "error": f"行程 {itinerary_id} 版本 {base_version} 不存在",
                "agent_trace": trace,
            }

        old_dict = old_itinerary.model_dump()

        # ── 2. 获取替代资源（如需要） ──────────────────────────────
        replacement_places = []
        if self._fetch_alternatives and action in (
            "replace_attraction", "replace_restaurant", "change_to_indoor",
        ):
            try:
                alt = self._fetch_alternatives(
                    original_place_id=target_item_id,
                    constraints=new_constraints,
                )
                replacement_places = alt or []
                trace.append({
                    "step": 2,
                    "agent": "adjustment_agent",
                    "action": "fetch_alternatives",
                    "summary": f"获取了 {len(replacement_places)} 个替代地点",
                    "status": "success",
                })
            except Exception as exc:
                logger.warning("获取替代地点失败: %s", exc)

        # ── 3. 锁定不受影响的天/项 ────────────────────────────────
        try:
            cloned = clone_for_modification(old_itinerary)
        except Exception as exc:
            return {
                "error": f"克隆行程失败: {exc}",
                "agent_trace": trace,
            }

        cloned_dict = cloned.model_dump(mode="json")

        # 锁定全部，然后解锁受影响的天
        lock_items_except(cloned, except_ids=[])
        if target_day:
            affected_ids = [it.get("item_id", "") for it in _day_items(cloned_dict, target_day)]
            unlock_items(cloned, affected_ids)

        locked_items = []
        unlocked_items = []
        for day in cloned_dict.get("days", []):
            for item in day.get("items", []):
                if item.get("locked"):
                    locked_items.append(item.get("item_id", ""))
                else:
                    unlocked_items.append(item.get("item_id", ""))

        # ── 4. LLM 局部重规划 ──────────────────────────────────────
        trace.append({
            "step": 3,
            "agent": "adjustment_agent",
            "action": "local_replan",
            "summary": f"受影响天: {target_day}",
            "status": "in_progress",
        })

        prompt = LOCAL_REPLAN_PROMPT.format(
            current_itinerary=json.dumps(cloned_dict, ensure_ascii=False, indent=2),
            action=action,
            target_day=target_day or "全部",
            target_item_id=target_item_id or "未指定",
            new_constraints=json.dumps(new_constraints, ensure_ascii=False),
            original_text=original_text or "（无）",
            locked_items=json.dumps(locked_items, ensure_ascii=False),
            unlocked_items=json.dumps(unlocked_items, ensure_ascii=False),
            replacement_places=json.dumps(replacement_places, ensure_ascii=False, indent=2),
            replacement_routes="[]",
        )

        try:
            raw = self._llm(prompt)
            replan_result = _parse_json(raw)
        except Exception as exc:
            logger.error("局部重规划 LLM 调用失败: %s", exc)
            trace.append({
                "step": 4,
                "agent": "adjustment_agent",
                "action": "llm_failed",
                "summary": str(exc),
                "status": "error",
            })
            return {
                "error": f"局部重规划失败: {exc}",
                "itinerary": old_dict,
                "agent_trace": trace,
            }

        # ── 5. 合并重规划结果 ──────────────────────────────────────
        affected_days_set: set[int] = set()
        replan_days = replan_result.get("days", [])
        for rday in replan_days:
            day_num = rday.get("day")
            if not day_num:
                continue
            affected_days_set.add(day_num)
            # 替换对应天的 items
            for orig_day in cloned_dict.get("days", []):
                if orig_day.get("day") == day_num and "items" in rday:
                    orig_day["items"] = rday["items"]

        # ── 6. 重新计算预算 ─────────────────────────────────────────
        try:
            budget = calculate_budget(cloned_dict, requirements or {}).model_dump()
        except Exception as exc:
            logger.warning("预算计算失败: %s", exc)
            budget = None

        # ── 7. 硬约束校验 ──────────────────────────────────────────
        if places:
            enrich_items_with_places(cloned_dict, places)
        evaluation = validate_hard_constraints(cloned_dict, requirements or {})

        # ── 8. 保存新版本 ───────────────────────────────────────────
        try:
            cloned.version = base_version + 1
            cloned.parent_version = base_version
            saved = save_version(cloned)
        except Exception as exc:
            logger.warning("保存版本失败: %s", exc)
            saved = cloned

        # ── 9. 计算 diff ────────────────────────────────────────────
        diff = diff_versions(itinerary_id, base_version, saved.version)

        trace.append({
            "step": 5,
            "agent": "adjustment_agent",
            "action": "save_version",
            "summary": f"保存版本 {saved.version}",
            "status": "success",
        })

        return {
            "itinerary": cloned_dict,
            "evaluation": evaluation.model_dump(),
            "budget": budget,
            "diff": diff.model_dump() if diff else None,
            "agent_trace": trace,
            "affected_days": sorted(affected_days_set),
        }


# ====================================================================
# 内部辅助
# ====================================================================


def _d(obj) -> dict:
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "dict"):
        return obj.dict()
    return {}


def _parse_json(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        first_nl = text.index("\n")
        start = first_nl + 1
        end = text.rfind("```")
        if end > start:
            text = text[start:end].strip()
        else:
            text = text[first_nl + 1:].strip()
    return json.loads(text)


def _day_items(itinerary: dict, day_num: int) -> list[dict]:
    """获取指定天数的所有行程项。"""
    for day in itinerary.get("days", []):
        if day.get("day") == day_num:
            return day.get("items", [])
    return []
