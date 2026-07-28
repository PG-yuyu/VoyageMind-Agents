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
import uuid
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
        llm_callable: Callable[[str], str] | None = None,
        alternative_place_fetcher: Callable | None = None,
    ):
        """
        Args:
            llm_callable: LLM 调用函数, 签名 (prompt: str) -> str
            alternative_place_fetcher: 获取替代地点的函数，签名:
                (original_place_id, constraints) -> list[dict]
        """
        self._llm = llm_callable
        if self._llm is None:
            self._llm = self._resolve_llm()
        self._fetch_alternatives = alternative_place_fetcher

    @staticmethod
    def _resolve_llm() -> Callable[[str], str]:
        """自动解析 LLM：优先 DeepSeekLLM，失败则 fallback 到 _demo_llm。

        _demo_llm 会解析 prompt 中的行程数据并做基本的结构化调整，
        确保即使无 API Key 也能看到修改效果。"""
        try:
            from backend.clients.deepseek_llm import DeepSeekLLM
            llm = DeepSeekLLM()
            logger.info("AdjustmentAgent: 已接入 DeepSeekLLM")
            return llm
        except (ImportError, ValueError) as exc:
            logger.warning(
                "AdjustmentAgent: DeepSeekLLM 不可用 (%s), 使用 Demo LLM", exc,
            )
            return _demo_llm

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
        current_itinerary_dict = req.get("current_itinerary")

        trace: list[dict] = []
        trace.append({
            "step": 1,
            "agent": "adjustment_agent",
            "action": "receive_modification",
            "summary": f"收到修改: {action}",
            "status": "success",
        })

        # ── 1. 获取当前行程 ────────────────────────────────────────
        old_itinerary = None
        old_dict = None

        # 优先使用前端直接传入的行程（绕过版本库）
        logger.warning(
            "🔍 ADJUST DEBUG: current_itinerary 是否传入=%s, 类型=%s, has_days=%s",
            current_itinerary_dict is not None,
            type(current_itinerary_dict).__name__ if current_itinerary_dict is not None else "N/A",
            bool(current_itinerary_dict.get("days")) if isinstance(current_itinerary_dict, dict) else False,
        )
        if isinstance(current_itinerary_dict, dict) and current_itinerary_dict.get("days"):
            old_dict = current_itinerary_dict
            # 修正前端传入的浮点数 walking_distance_m
            for d in old_dict.get("days", []):
                w = d.get("walking_distance_m")
                if isinstance(w, float):
                    d["walking_distance_m"] = int(round(w))
            # 清除 _place.description 历史污染（RAG 长文本可能被误写入 description）
            for d in old_dict.get("days", []):
                for item in d.get("items", []):
                    p = item.get("_place") or {}
                    desc = p.get("description") or ""
                    if len(desc) > 120:
                        p["description"] = ""  # 清空污染，保留 rag_description 用于弹窗
                    item["_place"] = p if p else item.get("_place")
            try:
                from backend.schemas.itinerary import Itinerary
                old_itinerary = Itinerary(**old_dict)
                logger.warning(
                    "🔍 ADJUST DEBUG: 使用前端直传行程 id=%s, days=%d, 第1天items=%d",
                    old_dict.get("itinerary_id", "?"),
                    len(old_dict.get("days", [])),
                    len(old_dict.get("days", [{}])[0].get("items", [])) if old_dict.get("days") else 0,
                )
            except Exception as _parse_exc:
                logger.warning("🔍 ADJUST DEBUG: 前端传入行程解析失败 (%s)，回退到版本库查询", _parse_exc)

        # 降级：版本库查询
        if old_itinerary is None:
            old_itinerary = get_itinerary(itinerary_id, base_version)
            if old_itinerary is not None:
                old_dict = old_itinerary.model_dump()

        if old_itinerary is None or old_dict is None:
            return {
                "error": f"行程 {itinerary_id} 不存在且未传入 current_itinerary",
                "agent_trace": trace,
            }

        # ── 2. 解析目标项 + 获取替代资源 ──────────────────────────
        # 如果前端没传 target_item_id，从用户文本中匹配行程项
        resolved_place_id: str | None = None
        if not target_item_id:
            logger.warning(
                "🔍 ADJUST DEBUG: 开始解析目标项 — action=%s, original_text=%s, days=%d",
                action, original_text, len(old_dict.get("days", [])),
            )
            target_item_id, resolved_place_id = _resolve_target_item(
                old_dict, original_text, action,
            )
            logger.warning(
                "🔍 ADJUST DEBUG: 解析结果 — item_id=%s, place_id=%s",
                target_item_id, resolved_place_id,
            )
        else:
            # 前端传了 item_id，查找对应的 place_id
            resolved_place_id = _find_place_id_by_item(old_dict, target_item_id)

        replacement_places = []
        if self._fetch_alternatives and action in (
            "replace_attraction", "replace_restaurant", "change_to_indoor",
        ):
            try:
                # change_to_indoor 需要室内过滤
                fetch_constraints = dict(new_constraints or {})
                if action == "change_to_indoor":
                    fetch_constraints["indoor"] = True
                alt = self._fetch_alternatives(
                    original_place_id=resolved_place_id or target_item_id,
                    constraints=fetch_constraints,
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

        # 锁定全部，然后解锁受影响的天（LLM 需要调整整天的时序）
        lock_items_except(cloned, except_ids=[])
        if target_day:
            affected_ids = [it.get("item_id", "") for it in _day_items(cloned_dict, target_day)]
            unlock_items(cloned, affected_ids)

        # 全局动作（reduce_walking / change_budget）：无论 target_day 是否设置，解锁所有天的景点项
        if action in ("reduce_walking", "change_budget", "change_to_indoor"):
            for day in cloned.days:
                for item in day.items:
                    if item.item_type.value == "attraction":
                        item.locked = False

        # 刷新快照：解锁操作修改了 cloned 对象，cloned_dict 需要重新序列化
        cloned_dict = cloned.model_dump(mode="json")

        locked_items = []
        unlocked_items = []
        for day in cloned_dict.get("days", []):
            for item in day.get("items", []):
                if item.get("locked"):
                    locked_items.append(item.get("item_id", ""))
                else:
                    unlocked_items.append(item.get("item_id", ""))

        logger.warning(
            "🔍 ADJUST LOCK: action=%s target_day=%s target_item_id=%s | locked=%d unlocked=%d",
            action, target_day, target_item_id, len(locked_items), len(unlocked_items),
        )
        for item_id in unlocked_items[:5]:
            logger.warning("🔍 ADJUST LOCK:   unlocked: %s", item_id)

        # ── 4. 大模型局部重规划 ──────────────────────────────────
        trace.append({
            "step": 3, "agent": "adjustment_agent",
            "action": "local_replan",
            "summary": f"目标: {target_item_id}",
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

        # 优先大模型，失败则降级。
        # 全局动作（reduce_walking / change_budget）：LLM 对多天行程常只返回 1 天，
        # 直接走确定性 demo 路径，保证所有天都被处理。
        replan_days = []
        replan_notes = []
        affected_days_set: set[int] = set()
        llm_used = False
        llm_raw = ""

        # reduce_walking / change_budget 走确定性 demo（LLM 对多天处理不可靠）
        # change_to_indoor 让 LLM 决策，demo 仅做降级兜底
        skip_llm = action in ("reduce_walking", "change_budget")

        if not skip_llm:
            try:
                raw = self._llm(prompt)
                llm_raw = raw[:500]
                result = _parse_json(raw)
                replan_days = result.get("days", [])
                replan_notes = result.get("replan_notes", [])
                llm_used = True
                logger.warning(
                    "🔍 ADJUST LLM: success | days=%d notes=%d raw_preview=%.200s",
                    len(replan_days), len(replan_notes), llm_raw,
                )
            except Exception as _llm_exc:
                logger.warning("🔍 ADJUST LLM: FAILED — %s", _llm_exc)

        # 大模型失败或产出明显错误 → 降级
        if not llm_used or not replan_days:
            logger.warning(
                "🔍 ADJUST FALLBACK: LLM failed or empty, falling to demo. llm_used=%s replan_days=%d",
                llm_used, len(replan_days),
            )
            try:
                raw = _demo_llm(prompt, alt_places=replacement_places)
                logger.warning("🔍 ADJUST DEMO: raw response (first 300 chars): %.300s", raw)
                result = _parse_json(raw)
                replan_days = result.get("days", [])
                replan_notes = result.get("replan_notes", [])
                llm_used = False
                logger.warning(
                    "🔍 ADJUST DEMO: parsed | days=%d notes=%s",
                    len(replan_days), replan_notes,
                )
            except Exception as e:
                logger.warning("🔍 ADJUST DEMO: FAILED — %s", e)
                return {"error": f"局部重规划失败: {e}", "itinerary": old_dict, "agent_trace": trace}

        trace.append({
            "step": 4, "agent": "adjustment_agent",
            "action": "llm_success" if llm_used else "demo_fallback",
            "summary": f"{'LLM' if llm_used else 'Demo'} 返回 {len(replan_days)} 天: {replan_notes[:3]}",
            "detail": llm_raw,
            "status": "success",
        })

        # ── 4.5. 强制还原 locked items ─────────────────────────────
        # LLM/demo 可能意外修改了 locked 项的 note/title/cost 等字段，
        # 用 old_dict 中的原始数据完全覆盖，确保未修改项 100% 不变。
        locked_set = set(locked_items)
        old_items_by_id: dict[str, dict] = {}
        for od in old_dict.get("days", []):
            for oi in od.get("items", []):
                iid = oi.get("item_id", "")
                if iid:
                    old_items_by_id[iid] = dict(oi)
        for rday in replan_days:
            for item in rday.get("items", []):
                iid = item.get("item_id", "")
                if iid in locked_set:
                    orig = old_items_by_id.get(iid)
                    if orig:
                        # 保留原始 item 的所有字段
                        item.clear()
                        item.update(orig)

        # ── 5. 质量验证 + 合并 ───────────────────────────────────
        logger.warning(
            "🔍 ADJUST MERGE: starting | replan_days=%d is_global=%s target_item_id=%s",
            len(replan_days), action in ("reduce_walking", "change_budget", "change_to_indoor"), target_item_id,
        )
        for rday in replan_days:
            day_num = rday.get("day")
            if not day_num:
                logger.warning("🔍 ADJUST MERGE: skipping rday with no day number")
                continue
            affected_days_set.add(day_num)

            # 全局动作（reduce_walking / change_budget）：不需要目标项，直接合并
            is_global_action = action in ("reduce_walking", "change_budget", "change_to_indoor")

            if not target_item_id and not is_global_action:
                # 无法确定目标项时，拒绝修改（安全优先）
                logger.warning("未找到目标项，拒绝修改")
                trace.append({"step": 35, "action": "no_target", "summary": "未找到目标项", "status": "error"})
                continue  # 跳过此天，不合并

            if is_global_action:
                # 全局动作：接受 replan_days 的所有项（过滤无 ID 的幻觉项、去重 place_id）
                seen_pids: set[str] = set()
                validated = []
                for it in rday.get("items", []):
                    iid = it.get("item_id", "")
                    if not iid:
                        continue
                    pid = it.get("place_id") or ""
                    itype = it.get("item_type", "")
                    # 景点去重：同一 place_id 只保留第一次出现
                    if itype == "attraction" and pid:
                        if pid in seen_pids:
                            logger.warning("🔍 ADJUST MERGE: 重复景点 %s (%s) 已跳过", pid, iid)
                            continue
                        seen_pids.add(pid)
                    validated.append(it)
                rday["items"] = validated
            else:
                # 保护非目标项（无论 LLM 还是 Demo 都需要）
                for orig_day in old_dict.get("days", []):
                    if orig_day.get("day") == day_num:
                        orig_by_id = {it.get("item_id",""): dict(it) for it in orig_day.get("items",[]) if it.get("item_id")}
                        validated = []
                        kept_ids = set()
                        for item in rday.get("items", []):
                            iid = item.get("item_id") or ""
                            orig = orig_by_id.get(iid)
                            if not iid:
                                continue  # 丢弃无 ID 的幻觉项
                            if iid == target_item_id:
                                # 目标项：保留大模型的修改，但补全 place_id（大模型可能只改 note）
                                if item.get("place_id") == orig.get("place_id") and replacement_places:
                                    alt = replacement_places[0]
                                    item["place_id"] = alt.get("place_id", item["place_id"])
                                    item["_place"] = alt
                                validated.append(item)
                            else:
                                # 非目标项：完整保留原始值
                                validated.append(orig)
                            kept_ids.add(iid)
                        # 补回遗漏的原始项
                        for iid, orig in orig_by_id.items():
                            if iid not in kept_ids:
                                validated.append(orig)
                        rday["items"] = validated
                        break

            # 合并到 cloned_dict
            for orig_day in cloned_dict.get("days", []):
                if orig_day.get("day") == day_num:
                    merged_count = len(rday["items"])
                    orig_day["items"] = rday["items"]
                    logger.warning(
                        "🔍 ADJUST MERGE: day=%d merged_items=%d",
                        day_num, merged_count,
                    )
                    break

        logger.warning(
            "🔍 ADJUST MERGE: done | affected_days=%s | cloned_dict days=%d",
            sorted(affected_days_set),
            len(cloned_dict.get("days", [])),
        )
        for d in cloned_dict.get("days", []):
            items = d.get("items", [])
            logger.warning(
                "🔍 ADJUST MERGE:   day=%d items=%d locked=%d unlocked=%d",
                d.get("day"), len(items),
                sum(1 for it in items if it.get("locked")),
                sum(1 for it in items if not it.get("locked")),
            )

        # ── 6. 重建 Itinerary 对象 + 保存 + 返回 ──────────────────
        try:
            cloned_dict_obj = cloned.model_dump(mode="json")
            for orig_day in cloned_dict_obj.get("days", []):
                # 修正 walking_distance_m 浮点数
                w = orig_day.get("walking_distance_m")
                if isinstance(w, float):
                    orig_day["walking_distance_m"] = int(round(w))
                if orig_day.get("day") in affected_days_set:
                    for src_day in cloned_dict.get("days", []):
                        if src_day.get("day") == orig_day["day"]:
                            orig_day["items"] = src_day["items"]
                            break
            from backend.schemas.itinerary import Itinerary
            cloned = Itinerary(**cloned_dict_obj)
        except Exception as exc:
            logger.warning("同步 Itinerary 对象失败: %s", exc)

        try:
            budget = calculate_budget(cloned_dict, requirements or {}).model_dump()
        except Exception:
            budget = None

        if places:
            enrich_items_with_places(cloned_dict, places)
        evaluation = validate_hard_constraints(cloned_dict, requirements or {})

        try:
            # 确保基准版本已存入版本库（前端直传时可能未持久化）
            if old_itinerary is not None and get_itinerary(itinerary_id, base_version) is None:
                old_itinerary.version = base_version
                old_itinerary.parent_version = None
                save_version(old_itinerary)
                logger.warning(
                    "🔍 ADJUST: 基准版本 v%d 未持久化，已自动保存", base_version,
                )

            cloned.version = base_version + 1
            cloned.parent_version = base_version
            saved = save_version(cloned)
        except Exception:
            saved = cloned

        diff = diff_versions(itinerary_id, base_version, saved.version)
        if diff is None and old_dict is not None:
            # 版本库对比失败时，直接用字典对比兜底
            from backend.services.diff_service import compute_diff
            diff = compute_diff(old_dict, cloned_dict,
                                from_version=base_version, to_version=saved.version)
            logger.warning(
                "🔍 ADJUST: diff_versions 返回 None，已用 compute_diff 兜底, changes=%d",
                len(diff.changes) if diff else 0,
            )

        trace.append({
            "step": 5, "agent": "adjustment_agent",
            "action": "save_version",
            "summary": f"保存版本 {saved.version}",
            "status": "success",
        })

        from backend.services.version_service import model_dump_with_places
        final_itinerary = model_dump_with_places(cloned)

        logger.warning(
            "🔍 ADJUST RESULT: itinerary_id=%s version=%s days=%d total_items=%d affected=%s diff_changes=%d",
            final_itinerary.get("itinerary_id", "?"),
            final_itinerary.get("version", "?"),
            len(final_itinerary.get("days", [])),
            sum(len(d.get("items", [])) for d in final_itinerary.get("days", [])),
            sorted(affected_days_set),
            len(diff.changes) if diff else 0,
        )

        return {
            "itinerary": final_itinerary,
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
        if "\n" in text:
            first_nl = text.index("\n")
            start = first_nl + 1
            end = text.rfind("```")
            if end > start:
                text = text[start:end].strip()
            else:
                text = text[first_nl + 1:].strip()
        else:
            # 单行格式: ```json{...}```
            text = text[3:].strip()
            if text.endswith("```"):
                text = text[:-3].strip()
            if text.startswith("json"):
                text = text[4:].strip()
    return json.loads(text)


def _day_items(itinerary: dict, day_num: int) -> list[dict]:
    """获取指定天数的所有行程项。"""
    for day in itinerary.get("days", []):
        if day.get("day") == day_num:
            return day.get("items", [])
    return []


def _demo_llm(prompt: str, alt_places: list[dict] | None = None) -> str:
    """开发用占位 LLM 调用 — 无 API Key 时的自动降级方案。

    会解析 prompt 中的行程数据和修改意图，做基本的结构化调整，
    让前后端整条链路可以实际跑通、看到修改效果。

    Args:
        prompt: LLM prompt 文本
        alt_places: 替代地点列表（直接传入，比 prompt 解析更可靠）
    """

    import re

    # ── 1. 从 prompt 中提取当前行程 JSON ──────────────────────────
    itinerary_json = None
    # 格式: "## 当前完整行程\n{...json...}\n\n## 修改请求"
    m = re.search(
        r'## 当前完整行程\s*\n(.*?)\n\s*## 修改请求',
        prompt,
        re.DOTALL,
    )
    if m:
        raw = m.group(1).strip()
        try:
            itinerary_json = json.loads(raw)
        except json.JSONDecodeError:
            pass

    if not itinerary_json or "days" not in itinerary_json:
        return '{"days": [], "replan_notes": ["Demo LLM: 未能解析行程数据"]}'

    # ── 2. 提取修改参数 ──────────────────────────────────────────
    action = ""
    target_day = None
    target_item_id = ""
    new_constraints = "{}"
    action_m = re.search(r'动作类型[:\s]*(\S+)', prompt)
    if action_m:
        action = action_m.group(1)
    day_m = re.search(r'目标天[:\s]*(\d+)', prompt)
    if day_m:
        target_day = int(day_m.group(1))
    logger.warning(
        "🔍 DEMO ENTRY: action=%s target_day=%s (from prompt)",
        action, target_day,
    )
    item_m = re.search(r'目标行程项[:\s]*(\S+)', prompt)
    if item_m:
        target_item_id = item_m.group(1)
    const_m = re.search(r'新约束[:\s]*(\{.+\})', prompt, re.DOTALL)
    if not const_m:
        # 空约束 {} 匹配不到 .+，单独处理
        const_m = re.search(r'新约束[:\s]*(\{\s*\})', prompt)
    if const_m:
        new_constraints = const_m.group(1)

    # ── 3. 获取锁定项 ────────────────────────────────────────────
    locked_ids_str = ""
    # 匹配 "以下行程项已被锁定" 到 "## 替代资源" 之间的内容
    locked_m = re.search(
        r'已被锁定[^*]*?\n(.*?)(?:\n\s*##\s*替代资源|\n\s*##\s*可用路线)',
        prompt,
        re.DOTALL,
    )
    if not locked_m:
        # 降级：匹配 JSON 数组 [...]
        locked_m = re.search(r'\["[^]]*"\]', prompt)
    if locked_m:
        locked_ids_str = locked_m.group(1) if locked_m.lastindex else locked_m.group(0)
    locked_ids = set()
    for tok in re.findall(r"'([^']+)'", locked_ids_str):
        locked_ids.add(tok)

    # ── 4. 定位目标天，克隆 items ────────────────────────────────
    days = itinerary_json.get("days", [])
    if not target_day:
        # 默认修改第一天
        target_day = days[0]["day"] if days else 1

    target_day_obj = None
    for d in days:
        if d.get("day") == target_day:
            target_day_obj = d
            break

    if not target_day_obj:
        logger.warning(
            "🔍 DEMO: target_day_obj is None! target_day=%s days_count=%d",
            target_day, len(days),
        )
        return json.dumps({
            "days": [],
            "affected_days": [],
            "replan_notes": [f"Demo LLM: 未找到第 {target_day} 天"],
        }, ensure_ascii=False)

    original_items = target_day_obj.get("items", [])

    # ── 从用户输入提取关键词，用于精确匹配 ──────────
    # 从 prompt 中提取用户原话
    orig_text = ""
    orig_text_m = re.search(r'用户原话[:\s]*(\S.*?)(?:\n\s*(?:##|$|- ))', prompt)
    if not orig_text_m:
        orig_text_m = re.search(r'用户原话[:\s]*(.*?)(?:\n|$)', prompt)
    if orig_text_m:
        orig_text = orig_text_m.group(1).strip()
        if orig_text == "（无）":
            orig_text = ""
    keywords = _extract_keywords(orig_text, action)
    # ── 替代资源：优先用参数传入的，否则从 prompt 解析 ──────────
    if alt_places is None:
        alt_places = []
        alt_m = re.search(
            r'## 替代资源[^\n]*\n(.*?)(?:\n\s*##\s*可用路线|\n\s*##\s*必须遵守)',
            prompt, re.DOTALL,
        )
        if alt_m:
            alt_raw = alt_m.group(1).strip()
            if alt_raw and alt_raw != "[]":
                try:
                    alt_places = json.loads(alt_raw)
                except json.JSONDecodeError:
                    pass
    logger.info("Demo LLM: action=%s keywords=%s alt_places=%d orig_text=%s",
                action, keywords, len(alt_places), orig_text[:60])

    # ── reduce_walking 全局处理：遍历所有天 ──────────────────────
    if action == "reduce_walking":
        logger.warning(
            "🔍 DEMO REDUCE: days=%d locked_ids=%d",
            len(days), len(locked_ids),
        )
        all_result_days = []
        all_change_log = []
        for d in days:
            day_num = d.get("day", 1)
            day_items = d.get("items", [])
            day_modified = []
            day_compressed = False
            last_attr_idx = -1

            for idx, item in enumerate(day_items):
                iid = item.get("item_id", "")
                it = dict(item)
                if iid in locked_ids or item.get("locked"):
                    day_modified.append(it)
                    continue
                if it.get("item_type") == "attraction":
                    last_attr_idx = len(day_modified)
                    dur = it.get("duration_minutes", 60)
                    logger.warning(
                        "🔍 DEMO REDUCE: day=%d item=%s type=%s dur=%d locked=%s",
                        day_num, iid, it.get("item_type"), dur, item.get("locked"),
                    )
                    if dur > 90:
                        it["duration_minutes"] = int(dur * 0.6)
                        it["end_time"] = _shift_time(it["start_time"], it["duration_minutes"])
                        it["note"] = "步行强度已降低（Demo LLM）"
                        day_compressed = True
                        all_change_log.append(f"Day{day_num} {it.get('item_id','')} 时长压缩")
                day_modified.append(it)

            # 若无景点可压缩，移除最后一个景点以减少步行
            if not day_compressed and last_attr_idx >= 0:
                removed = day_modified.pop(last_attr_idx)
                all_change_log.append(
                    f"Day{day_num} 移除景点 {removed.get('item_id','')} 以减少步行"
                )
                logger.warning(
                    "🔍 DEMO REDUCE: day=%d no compressible attractions, removing last: %s",
                    day_num, removed.get("item_id"),
                )

            new_cost = sum(float(it.get("total_cost", 0) or 0) for it in day_modified)
            all_result_days.append({
                "day": day_num,
                "date": d.get("date", ""),
                "items": day_modified,
                "daily_cost": round(new_cost, 2),
                "walking_distance_m": d.get("walking_distance_m", 0),
                "start_time": day_modified[0]["start_time"] if day_modified else "09:00",
                "end_time": day_modified[-1]["end_time"] if day_modified else "18:00",
            })

        if not all_change_log:
            # 极端兜底：没有任何可操作项
            all_change_log.append("已尝试减少步行（无可压缩景点或移除项）")

        result = {
            "days": all_result_days,
            "affected_days": [d.get("day") for d in days],
            "replan_notes": all_change_log,
        }
        logger.info("Demo LLM reduce_walking: %d days, changes=%d",
                    len(all_result_days), len(all_change_log))
        return json.dumps(result, ensure_ascii=False)

    # ── change_to_indoor 全局处理：遍历所有天，替换户外景点为室内 ──
    if action == "change_to_indoor":
        # 只取景点类型，排除误入的餐厅
        indoor_places = [
            p for p in (alt_places or [])
            if isinstance(p, dict) and p.get("place_type") == "attraction"
        ]
        all_result_days = []
        all_change_log = []
        indoor_idx = 0
        for d in days:
            day_num = d.get("day", 1)
            day_items = d.get("items", [])
            day_modified = []
            for item in day_items:
                iid = item.get("item_id", "")
                it = dict(item)
                if iid in locked_ids or item.get("locked"):
                    day_modified.append(it)
                    continue
                if it.get("item_type") == "attraction":
                    place = it.get("_place") or {}
                    tags = place.get("tags", []) or []
                    is_indoor = any("室内" in (t or "") for t in tags)
                    if is_indoor:
                        day_modified.append(it)
                        continue
                    # 户外景点 → 尝试替换为室内
                    if indoor_idx < len(indoor_places):
                        alt = indoor_places[indoor_idx]
                        indoor_idx += 1
                        it["place_id"] = alt.get("place_id", it.get("place_id", ""))
                        it["_place"] = alt
                        it["note"] = alt.get("name", "室内替代景点")
                        if alt.get("price") is not None:
                            it["cost_per_person"] = float(alt["price"])
                            it["total_cost"] = float(alt["price"])
                        all_change_log.append(
                            f"Day{day_num} {iid} → 室内: {alt.get('name', '替代')}"
                        )
                    else:
                        # 无替代资源：保留原景点，仅加备注
                        it["note"] = (it.get("note") or "") + "（建议替换为室内）"
                        all_change_log.append(f"Day{day_num} {iid} 无室内替代，保留")
                day_modified.append(it)
            new_cost = sum(float(it.get("total_cost", 0) or 0) for it in day_modified)
            all_result_days.append({
                "day": day_num, "date": d.get("date", ""), "items": day_modified,
                "daily_cost": round(new_cost, 2),
                "walking_distance_m": d.get("walking_distance_m", 0),
                "start_time": day_modified[0]["start_time"] if day_modified else "09:00",
                "end_time": day_modified[-1]["end_time"] if day_modified else "18:00",
            })
        if not all_change_log:
            all_change_log.append("未找到可替换的户外景点，行程保持不变")
        result = {
            "days": all_result_days,
            "affected_days": [d.get("day") for d in days],
            "replan_notes": all_change_log,
        }
        logger.info("Demo LLM change_to_indoor: %d days, changes=%d",
                    len(all_result_days), len(all_change_log))
        return json.dumps(result, ensure_ascii=False)

    modified_items = []
    change_log = []

    for item in original_items:
        iid = item.get("item_id", "")
        # 锁定项不动
        if iid in locked_ids or item.get("locked"):
            modified_items.append(dict(item))
            continue

        it = dict(item)  # 浅拷贝，准备修改
        item_type = it.get("item_type", "")
        place_id = it.get("place_id", "")
        note = it.get("note", "") or ""
        # 从 _place 引用或 note 中获取可搜索文本
        place_ref = it.get("_place") or {}
        search_text = f"{place_ref.get('name', '')} {note} {place_id}".lower()

        # ── 关键词匹配：有关键词时只改匹配项 ──────────
        if keywords and not _match_keywords(search_text, keywords):
            modified_items.append(it)
            continue

        if action == "replace_attraction" and item_type == "attraction":
            # 替换景点：优先用推荐服务返回的真实替代地点
            alt_place = _pick_replacement(alt_places, item_type)
            if alt_place:
                it["place_id"] = alt_place.get("place_id", it.get("place_id", ""))
                it["_place"] = alt_place
                it["note"] = alt_place.get("name", f"替代{_describe_item(it)}")
                if alt_place.get("price"):
                    it["total_cost"] = float(alt_place["price"])
                change_log.append(
                    f'{it.get("item_id","")} → {alt_place.get("name","替代景点")}'
                )
            else:
                it["place_id"] = f"alt_{place_id}" if place_id else "alt_place_001"
                it["note"] = f"已替换原{_describe_item(it)}为替代景点，满足用户偏好"
                it["total_cost"] = max(0, (it.get("total_cost", 0) or 0) - 10)
                change_log.append(f'{it.get("item_id","")} 替换景点(无候选)')
        elif action == "change_budget":
            # 调整预算
            if it.get("total_cost", 0) > 50:
                it["total_cost"] = round(it["total_cost"] * 0.8, 2)
                it["note"] = "费用已优化（Demo LLM）"
                change_log.append(f"{it.get('item_id','')} 费用降低")
        else:
            # 通用：加个标记
            if item_type == "attraction":
                it["note"] = "已调整（Demo LLM）" if not note else note
                change_log.append(f"{it.get('item_id','')} 标记调整")

        modified_items.append(it)

    # ── 5. 若无任何变化，给第一个非锁定项加个 note ────────────────
    if not change_log:
        for it in modified_items:
            if it.get("item_id", "") not in locked_ids and not it.get("locked"):
                it["note"] = "已调整（Demo LLM）"
                change_log.append(f"{it.get('item_id','')} 标记调整")
                break

    # 重算 daily_cost 和 walking_distance_m
    new_daily_cost = sum(
        float(it.get("total_cost", 0) or 0) for it in modified_items
    )

    result_day = {
        "day": target_day,
        "date": target_day_obj.get("date", ""),
        "items": modified_items,
        "daily_cost": round(new_daily_cost, 2),
        "walking_distance_m": target_day_obj.get("walking_distance_m", 0),
        "start_time": modified_items[0]["start_time"] if modified_items else "09:00",
        "end_time": modified_items[-1]["end_time"] if modified_items else "18:00",
    }

    result = {
        "days": [result_day],
        "affected_days": [target_day],
        "replan_notes": change_log,
    }

    logger.info("Demo LLM 生成修改: action=%s, day=%s, changes=%d",
                action, target_day, len(change_log))
    return json.dumps(result, ensure_ascii=False)


def _pick_replacement(replacement_places: list[dict], item_type: str) -> dict | None:
    """从替代资源列表中选一个同类型的地点。"""
    candidates = [
        p for p in replacement_places
        if isinstance(p, dict) and p.get("place_type") == item_type
    ]
    if not candidates:
        candidates = [p for p in replacement_places if isinstance(p, dict)]
    return candidates[0] if candidates else None


def _resolve_target_item(
    itinerary: dict, original_text: str, action: str,
) -> tuple[str | None, str | None]:
    """从用户文本中解析目标行程项 (item_id, place_id)。

    在没有 target_item_id 时，搜索所有行程项的名称/note，
    找到与用户描述最匹配的那个。
    """
    if not original_text:
        return None, None
    keywords = _extract_keywords(original_text, action)
    if not keywords:
        return None, None
    # 按长度降序：最长关键词最具体
    keywords.sort(key=len, reverse=True)
    best_item_id = None
    best_place_id = None
    best_score = 0
    import logging as _logging
    _log = _logging.getLogger(__name__)
    _log.warning("🔍 RESOLVE: keywords=%s, searching %d days", keywords, len(itinerary.get("days", [])))
    for day_data in itinerary.get("days", []):
        for item in day_data.get("items", []):
            itype = item.get("item_type", "")
            if itype not in ("attraction", "lunch", "dinner", "hotel"):
                continue
            place = item.get("_place") or {}
            note = item.get("note") or ""
            pid = item.get("place_id") or ""
            # 搜索文本：地名 + note + place_id
            search_text = f"{place.get('name', '')} {note} {pid}"
            _log.warning("🔍 RESOLVE: item_type=%s, has_place=%s, place_name=%s, note=%.40s",
                         itype, bool(item.get("_place")), place.get('name', '-'), note)
            # 计算匹配分数：最长命中的关键词长度
            score = 0
            for kw in keywords:
                if kw in search_text:
                    score = max(score, len(kw))
            if score > best_score:
                best_score = score
                best_item_id = item.get("item_id")
                best_place_id = pid
    _log.warning("🔍 RESOLVE: 匹配结果 — best_score=%d, item_id=%s, place_id=%s", best_score, best_item_id, best_place_id)
    return best_item_id, best_place_id


def _direct_replace(
    itinerary: dict,
    target_day: int | None,
    target_item_id: str | None,
    resolved_place_id: str | None,
    replacement_places: list[dict],
) -> bool:
    """直接替换行程项（LLM 不可用时的快速路径）。

    在指定天的 items 中，找到匹配 target_item_id 或 resolved_place_id 的项，
    用 replacement_places[0] 替换其地点信息。
    """
    if not replacement_places:
        return False
    alt = replacement_places[0]
    alt_name = alt.get("name", "替代景点")
    alt_pid = alt.get("place_id", "")

    target_day = target_day or 1
    for day_data in itinerary.get("days", []):
        if day_data.get("day") != target_day:
            continue
        for item in day_data.get("items", []):
            iid = item.get("item_id", "")
            pid = item.get("place_id", "")
            itype = item.get("item_type", "")
            # 匹配条件：item_id 相同，或 place_id 相同，或类型是 attraction
            if itype != "attraction":
                continue
            if target_item_id and iid != target_item_id:
                if resolved_place_id and pid != resolved_place_id:
                    continue
            # 执行替换
            logger.info("直接替换: %s (%s) → %s (%s)",
                        item.get("note") or pid, iid, alt_name, alt_pid)
            item["place_id"] = alt_pid
            item["_place"] = alt
            item["note"] = alt_name
            if alt.get("price") is not None:
                item["total_cost"] = float(alt["price"])
                item["cost_per_person"] = float(alt["price"])
            return True
    return False


def _find_place_id_by_item(itinerary: dict, item_id: str) -> str | None:
    """根据 item_id 查找对应的 place_id。"""
    for day_data in itinerary.get("days", []):
        for item in day_data.get("items", []):
            if item.get("item_id") == item_id:
                return item.get("place_id")
    return None


def _extract_keywords(original_text: str, action: str) -> list[str]:
    """从用户输入中提取关键词，用于精确匹配需要修改的行程项。

    例如 "不喜欢逛博物馆" → ["博物"]
        "把海河夜景换成其他的" → ["海河", "夜景"]
        "第三天的博物馆也换掉" → ["博物"]（过滤掉"第三天"和"也"）
        "太累了减少步行" → []（reduce_walking 不按关键词筛选）
    """
    if not original_text:
        return []

    # reduce_walking / change_budget / change_to_indoor 不按关键词筛选（全局调整）
    if action in ("reduce_walking", "change_budget", "change_to_indoor"):
        return []

    # 常见否定/替换前缀（按长度降序，同长时"替换"优先于"换成"避免拆坏"替换成"）
    prefixes = sorted(
        ["不喜欢", "不想", "不要", "替换", "换成", "换掉", "改成", "讨厌", "别", "把"],
        key=lambda x: (-len(x), x),
    )
    text = original_text
    for p in prefixes:
        text = text.replace(p, " ")

    # 常见的后缀词
    suffixes = ["的", "了", "吧", "嘛", "啊", "其他的", "别的", "逛"]
    for s in suffixes:
        text = text.replace(s, " ")

    # 提取 2-10 字的中文关键词（覆盖"张学良故居"等 5+ 字地名）
    import re
    words = re.findall(r"[一-龥]{2,10}", text)

    # ── 过滤噪音词 ──────────────────────────────────────────
    # 1. 天数/序号类关键词（第X天、一二三...）→ 过滤
    day_pattern = re.compile(r'^第[一二两三四五六七八九十\d]+天?$')
    number_chars = set('一二两三四五六七八九十百千万0123456789第天个')

    # 2. 常见连词/虚词，需要从关键词中剥离
    noise_chars = '也还都就只又再已经常总把被让给对跟和与及或但然而所以因为如果虽然'

    keywords = []
    for w in words:
        if not w or len(w) < 1:
            continue
        # 过滤纯天数/序号词
        if day_pattern.match(w):
            continue
        if all(c in number_chars for c in w):
            continue
        # 剥离噪音字后，如果还有内容就保留
        cleaned = w
        for c in noise_chars:
            cleaned = cleaned.replace(c, '')
        if cleaned and len(cleaned) >= 1:
            keywords.append(cleaned)
    return keywords


def _match_keywords(search_text: str, keywords: list[str]) -> bool:
    """检查 search_text 是否匹配关键词。按长度降序，至少最长的关键词要命中。"""
    if not keywords:
        return False
    # 按长度降序：最具体的关键词优先
    sorted_kw = sorted(keywords, key=len, reverse=True)
    # 最长的关键词必须命中（避免"博物"误匹配所有博物馆）
    if len(sorted_kw) >= 2 and len(sorted_kw[0]) >= 3 and sorted_kw[0] in search_text:
        return True
    # 单关键词或短关键词：需要至少一半命中
    hits = sum(1 for kw in keywords if kw in search_text)
    return hits >= max(1, len(keywords) // 2)


def _describe_item(item: dict) -> str:
    """用可读文本描述行程项，避免使用已被修改过的 note。"""
    place = item.get("_place") or {}
    name = place.get("name", "")
    if name:
        return name
    # 如果 note 已被 demo LLM 修改过（含"已替换""已调整"等），不要用
    note = item.get("note", "")
    if note and not any(note.startswith(p) for p in ("已替换", "已调整", "已修改", "已优化")):
        # 取第一个" — "之前的部分（防止描述叠加）
        clean = note.split(" — ")[0].strip()
        return clean[:15] if clean else note[:15]
    pid = item.get("place_id", "")
    if pid and not pid.startswith("alt_") and not pid.startswith("place_"):
        return pid
    return "行程项"


def _inject_place_refs(final_itinerary: dict, source_dict: dict) -> None:
    """为 final_itinerary 的所有 items 注入 _place 引用。

    model_dump(mode="json") 丢弃了非 schema 字段。从 PlaceRepository
    按 place_id 查找真实地点数据回注，确保前端能显示名称和坐标。
    """
    # 预加载地点索引
    place_by_id: dict[str, dict] = {}
    try:
        from backend.app.repositories import PlaceRepository
        repo = PlaceRepository()
        for p in repo.list_attractions() + repo.list_hotels() + repo.list_restaurants():
            pd = p.to_dict()
            pid = pd.get("place_id", "")
            if pid:
                place_by_id[pid] = pd
    except Exception:
        pass

    if not place_by_id:
        return

    for day_data in final_itinerary.get("days", []):
        for item in day_data.get("items", []):
            pid = item.get("place_id") or ""
            if not pid:
                continue
            # 从 PlaceRepository 查找真实地点
            db_place = place_by_id.get(pid)
            if db_place:
                item["_place"] = db_place
                # 修正 note：如果 note 是虚假描述或替换文本，改用真实地名
                note = item.get("note") or ""
                db_name = db_place.get("name", "")
                if db_name and (
                    not note
                    or note.startswith("已替换")
                    or note.startswith("已调整")
                    or "alt_" in pid
                ):
                    item["note"] = db_name
                continue
            # place_id 不在数据库中（可能是 demo LLM 的合成 ID 如 alt_xxx）
            # 尝试从 source_dict 的对应 item 中恢复原始 _place
            _recover_from_source(item, source_dict, place_by_id)


def _recover_from_source(
    item: dict, source_dict: dict, place_by_id: dict,
) -> None:
    """当 item 的 place_id 是合成 ID 时，从 source 或 note 中恢复真实地点。"""
    iid = item.get("item_id", "")
    note = item.get("note") or ""
    # 尝试 1：从 source 中同 item_id 的项恢复
    for day_data in source_dict.get("days", []):
        for src_item in day_data.get("items", []):
            if src_item.get("item_id") == iid:
                src_place = src_item.get("_place")
                if src_place and isinstance(src_place, dict) and src_place.get("place_id"):
                    src_pid = src_place["place_id"]
                    if src_pid in place_by_id:
                        item["_place"] = place_by_id[src_pid]
                        item["place_id"] = src_pid
                        item["note"] = place_by_id[src_pid].get("name", note)
                        return
    # 尝试 2：从 note 中提取地名，在 place_by_id 中模糊查找
    if note and len(note) >= 2:
        for pid, p in place_by_id.items():
            pname = p.get("name", "")
            if pname and (note in pname or pname in note):
                item["_place"] = p
                item["place_id"] = pid
                item["note"] = pname
                return


def _shift_time(start_time: str, duration_minutes: int) -> str:
    """计算结束时间。"""
    parts = start_time.split(":")
    if len(parts) != 2:
        return "18:00"
    h, m = int(parts[0]), int(parts[1])
    total = h * 60 + m + duration_minutes
    return f"{total // 60 % 24:02d}:{total % 60:02d}"
