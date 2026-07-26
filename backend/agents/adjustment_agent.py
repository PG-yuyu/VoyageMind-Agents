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
            # 记录 LLM 返回摘要到 trace
            days_count = len(replan_result.get("days", []))
            notes = replan_result.get("replan_notes", [])
            # 记录前 500 字符原始返回，便于调试
            raw_preview = raw[:500]
            trace.append({
                "step": 4,
                "agent": "adjustment_agent",
                "action": "llm_success",
                "summary": f"LLM 返回 {days_count} 天, notes: {notes[:3]}",
                "detail": raw_preview,
                "status": "success",
            })
            logger.info(
                "LLM 重规划成功: %d 天, notes=%s\n---LLM返回(raw)---\n%s\n---",
                days_count, notes[:3], raw_preview,
            )
        except Exception as exc:
            logger.error("局部重规划 LLM 调用失败: %s，降级到 Demo LLM", exc)
            trace.append({
                "step": 4,
                "agent": "adjustment_agent",
                "action": "llm_failed_fallback_demo",
                "summary": f"LLM 调用失败, 使用 Demo LLM 降级: {exc}",
                "status": "warning",
            })
            # ── 降级到 _demo_llm ──────────────────────────────────
            try:
                raw = _demo_llm(prompt)
                replan_result = _parse_json(raw)
                logger.info("Demo LLM 降级成功")
            except Exception as fallback_exc:
                logger.error("Demo LLM 降级也失败: %s", fallback_exc)
                return {
                    "error": f"局部重规划失败（LLM + 降级均不可用）: {exc}",
                    "itinerary": old_dict,
                    "agent_trace": trace,
                }

        # ── 5. 合并重规划结果 ──────────────────────────────────────
        affected_days_set: set[int] = set()
        replan_days = replan_result.get("days", [])
        # 如果 LLM 返回了有效 JSON 但没有实际修改任何天，自动降级
        if not replan_days:
            logger.warning("LLM 返回空 days，降级到 Demo LLM")
            trace.append({
                "step": 4,
                "agent": "adjustment_agent",
                "action": "llm_empty_fallback_demo",
                "summary": "LLM 返回空数据，使用 Demo LLM 降级",
                "status": "warning",
            })
            try:
                raw = _demo_llm(prompt)
                replan_result = _parse_json(raw)
                replan_days = replan_result.get("days", [])
            except Exception as fallback_exc:
                logger.error("Demo LLM 降级也失败: %s", fallback_exc)

        for rday in replan_days:
            day_num = rday.get("day")
            if not day_num:
                continue
            affected_days_set.add(day_num)
            # 替换对应天的 items
            for orig_day in cloned_dict.get("days", []):
                if orig_day.get("day") == day_num and "items" in rday:
                    # 保留被锁定的 item（LLM 可能误改）
                    orig_items = orig_day.get("items", [])
                    locked_map = {
                        it["item_id"]: it
                        for it in orig_items if it.get("locked") and it.get("item_id")
                    }
                    new_items = rday["items"]
                    merged = []
                    seen_ids: set[str] = set()
                    for item in new_items:
                        iid = item.get("item_id") or ""
                        if iid in locked_map:
                            merged.append(locked_map[iid])
                        else:
                            merged.append(item)
                        if iid:
                            seen_ids.add(iid)
                    # 补上 locked 但 LLM 没返回的项
                    for iid, locked_item in locked_map.items():
                        if iid not in seen_ids:
                            merged.append(locked_item)
                    orig_day["items"] = merged

        # ── 5.25 关键词过滤：只保留匹配用户意图的修改 ──────
        kw = _extract_keywords(original_text, action)
        if kw:
            logger.info("关键词过滤: action=%s, keywords=%s", action, kw)
            for day_num in sorted(affected_days_set):
                orig_items = _day_items(old_dict, day_num)
                new_items = _day_items(cloned_dict, day_num)
                # 为每个新 item 建索引
                orig_by_id = {it.get("item_id", ""): it for it in orig_items}
                new_by_id = {it.get("item_id", ""): it for it in new_items}
                for iid, new_it in new_by_id.items():
                    orig_it = orig_by_id.get(iid)
                    if not orig_it:
                        continue
                    # 检查是否有实际变化
                    pid_changed = new_it.get("place_id") != orig_it.get("place_id")
                    note_changed = (new_it.get("note") or "") != (orig_it.get("note") or "")
                    if pid_changed or note_changed:
                        # 检查是否匹配关键词
                        place_ref = new_it.get("_place") or orig_it.get("_place") or {}
                        search_text = f"{place_ref.get('name', '')} {orig_it.get('note', '')} {orig_it.get('place_id', '')}".lower()
                        if not _match_keywords(search_text, kw):
                            # 不匹配 → 回退到原始值
                            logger.info("回退非匹配项: %s (search_text=%s)", iid, search_text[:80])
                            new_it["place_id"] = orig_it.get("place_id")
                            new_it["note"] = orig_it.get("note")
                            new_it["total_cost"] = orig_it.get("total_cost")
            trace.append({
                "step": 38,
                "agent": "adjustment_agent",
                "action": "keyword_filter",
                "summary": f"关键词过滤: {kw}",
                "status": "success",
            })

        # ── 5.3 检查 LLM 是否真正修改了数据 ────────────────────
        # 比较受影响天的 place_id，如果全部相同则说明 LLM 没做修改
        llm_made_changes = False
        for day_num in sorted(affected_days_set):
            orig_items = _day_items(old_dict, day_num)
            new_items = _day_items(cloned_dict, day_num)
            orig_pids = [it.get("place_id", "") for it in orig_items]
            new_pids = [it.get("place_id", "") for it in new_items]
            orig_notes = [it.get("note", "") or "" for it in orig_items]
            new_notes = [it.get("note", "") or "" for it in new_items]
            if orig_pids != new_pids or orig_notes != new_notes:
                llm_made_changes = True
                break

        if not llm_made_changes and affected_days_set:
            logger.warning("LLM 返回了未修改的数据，降级到 Demo LLM")
            trace.append({
                "step": 44,
                "agent": "adjustment_agent",
                "action": "llm_no_changes_fallback_demo",
                "summary": "LLM 未做实际修改，使用 Demo LLM 降级",
                "status": "warning",
            })
            try:
                raw = _demo_llm(prompt)
                replan_result = _parse_json(raw)
                replan_days = replan_result.get("days", [])
                # 重新合并
                affected_days_set.clear()
                for rday in replan_days:
                    day_num = rday.get("day")
                    if not day_num:
                        continue
                    affected_days_set.add(day_num)
                    for orig_day in cloned_dict.get("days", []):
                        if orig_day.get("day") == day_num and "items" in rday:
                            orig_items = orig_day.get("items", [])
                            locked_map = {
                                it["item_id"]: it
                                for it in orig_items if it.get("locked") and it.get("item_id")
                            }
                            merged = []
                            seen_ids = set()
                            for item in rday["items"]:
                                iid = item.get("item_id") or ""
                                if iid in locked_map:
                                    merged.append(locked_map[iid])
                                else:
                                    merged.append(item)
                                if iid:
                                    seen_ids.add(iid)
                            for iid, lit in locked_map.items():
                                if iid not in seen_ids:
                                    merged.append(lit)
                            orig_day["items"] = merged
            except Exception as fallback_exc:
                logger.error("Demo LLM 降级也失败: %s", fallback_exc)

        # ── 5.5 补全新 items 的 item_id ──────────────────────────
        for orig_day in cloned_dict.get("days", []):
            if orig_day.get("day") not in affected_days_set:
                continue
            existing = set()
            for item in orig_day.get("items", []):
                if item.get("item_id"):
                    existing.add(item["item_id"])
            for idx, item in enumerate(orig_day.get("items", [])):
                if not item.get("item_id") or item["item_id"].endswith("_new"):
                    iid = f"day{orig_day['day']}_item_{idx:03d}_{uuid.uuid4().hex[:4]}"
                    while iid in existing:
                        iid = f"day{orig_day['day']}_item_{idx:03d}_{uuid.uuid4().hex[:4]}"
                    item["item_id"] = iid
                    existing.add(iid)

        # ── 5.6 将 merged 写回 Itinerary 对象（确保保存时一致） ──
        try:
            cloned_dict_obj = cloned.model_dump(mode="json")
            # 仅更新受影响天的 items
            for orig_day in cloned_dict_obj.get("days", []):
                if orig_day.get("day") in affected_days_set:
                    for merged_day in cloned_dict.get("days", []):
                        if merged_day.get("day") == orig_day["day"]:
                            orig_day["items"] = merged_day["items"]
                            break
            # 反序列化回 Itinerary 对象
            from backend.schemas.itinerary import Itinerary
            cloned = Itinerary(**cloned_dict_obj)
        except Exception as exc:
            logger.warning("同步 Itinerary 对象失败: %s", exc)

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

        # 用 Itinerary 对象的 model_dump（与存储一致的格式）
        final_itinerary = cloned.model_dump(mode="json")

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


def _demo_llm(prompt: str) -> str:
    """开发用占位 LLM 调用 — 无 API Key 时的自动降级方案。

    会解析 prompt 中的行程数据和修改意图，做基本的结构化调整，
    让前后端整条链路可以实际跑通、看到修改效果。
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
    logger.info("Demo LLM 关键词: action=%s, keywords=%s, orig_text=%s", action, keywords, orig_text[:60])
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

        if action == "change_to_indoor" and item_type == "attraction":
            # 户外景点 → 改为室内
            it["note"] = "已替换为室内方案（Demo LLM）" if not note else note + "；室内替代"
            it["place_id"] = f"{place_id}_indoor" if place_id else "indoor_place_001"
            it["total_cost"] = max(0, it.get("total_cost", 0) - 20)
            change_log.append(f"{it.get('start_time','')} {it.get('item_id','')} → 室内")
        elif action == "reduce_walking":
            # 减少步行：缩短部分景点的 duration
            if item_type == "attraction" and it.get("duration_minutes", 60) > 90:
                it["duration_minutes"] = int(it["duration_minutes"] * 0.6)
                it["end_time"] = _shift_time(it["start_time"], it["duration_minutes"])
                it["note"] = "步行强度已降低（Demo LLM）"
                change_log.append(f"{it.get('item_id','')} 时长压缩")
        elif action == "replace_attraction" and item_type == "attraction":
            # 替换景点：换个 place_id 并加 note
            it["place_id"] = f"alt_{place_id}" if place_id else "alt_place_001"
            it["note"] = f"已替换原{_describe_item(it)}为替代景点，满足用户偏好"
            it["total_cost"] = max(0, (it.get("total_cost", 0) or 0) - 10)
            change_log.append(f"{it.get('item_id','')} 替换景点")
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


def _extract_keywords(original_text: str, action: str) -> list[str]:
    """从用户输入中提取关键词，用于精确匹配需要修改的行程项。

    例如 "不喜欢逛博物馆" → ["博物"]
        "把海河夜景换成其他的" → ["海河", "夜景"]
        "第三天的博物馆也换掉" → ["博物"]（过滤掉"第三天"和"也"）
        "太累了减少步行" → []（reduce_walking 不按关键词筛选）
    """
    if not original_text:
        return []

    # reduce_walking / change_budget 不按关键词筛选（全局调整）
    if action in ("reduce_walking", "change_budget"):
        return []

    # 常见的否定/替换前缀，去掉后剩下的就是目标关键词
    prefixes = ["不喜欢", "不想", "不要", "别", "讨厌", "换掉", "换成", "替换", "把", "改成"]
    text = original_text
    for p in prefixes:
        text = text.replace(p, " ")

    # 常见的后缀词
    suffixes = ["的", "了", "吧", "嘛", "啊", "其他的", "别的", "逛"]
    for s in suffixes:
        text = text.replace(s, " ")

    # 提取 1-4 字的中文关键词
    import re
    words = re.findall(r"[一-龥]{1,4}", text)

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
    """检查 search_text 是否匹配任意关键词。"""
    for kw in keywords:
        if kw in search_text:
            return True
    return False


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


def _shift_time(start_time: str, duration_minutes: int) -> str:
    """计算结束时间。"""
    parts = start_time.split(":")
    if len(parts) != 2:
        return "18:00"
    h, m = int(parts[0]), int(parts[1])
    total = h * 60 + m + duration_minutes
    return f"{total // 60 % 24:02d}:{total % 60:02d}"
