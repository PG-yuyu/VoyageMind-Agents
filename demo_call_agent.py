"""
Agent 调用演示 — 如何调你写的 PlanningAgent 和 AdjustmentAgent
==============================================================

三种调用模式:
  1. Mock LLM — 测试流程，不依赖真实大模型
  2. 接入真实 LLM — 连接 OpenAI/Claude API
  3. 通过 FastAPI — 走 HTTP API

运行:
  python demo_call_agent.py         # 模式1: Mock LLM
  python demo_call_agent.py --llm   # 模式2: 真实 LLM（需配置 API Key）
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent
os.chdir(ROOT)

# ── 颜色 ──────────────────────────────────────────
import sys
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

C = "\033[96m"; G = "\033[92m"; Y = "\033[93m"; R = "\033[91m"; B = "\033[1m"; E = "\033[0m"

def h(title): print(f"\n{B}{'='*60}{E}\n{B}{title}{E}\n{B}{'='*60}{E}")
def ok(m):    print(f"  {G}[OK]{E} {m}")
def info(m):  print(f"  {C}[..]{E} {m}")
def warn(m):  print(f"  {Y}[!]{E} {m}")


# ═══════════════════════════════════════════════════
# 1. Mock LLM — 不调真实模型，只返回固定 JSON
# ═══════════════════════════════════════════════════

class MockLLM:
    """模拟 LLM，返回从 mock 文件读取的预设数据。

    用于测试 Agent 流程、状态机、校验循环是否正确。
    """

    def __init__(self):
        self.call_count = 0
    def _fill_item(self, item: dict, day: int, idx: int) -> dict:
        """补全 items 缺失的必填字段。"""
        base = {"item_id": f"day{day}_item_{idx:03d}", "day": day,
                "duration_minutes": 60, "cost_per_person": 0, "total_cost": 0,
                "route_from_previous_id": None, "note": None, "locked": False}
        base.update(item)
        return base

    def _fill_day(self, day_dict: dict) -> dict:
        """补全天数据。"""
        day = day_dict["day"]
        items = [self._fill_item(it, day, i) for i, it in enumerate(day_dict.get("items", []))]
        walking = sum(it.get("_est_walking", 0) for it in day_dict.get("items", []))
        return {
            "day": day,
            "date": day_dict.get("date", "2026-07-25"),
            "items": items,
            "daily_cost": sum(it.get("total_cost", 0) or 0 for it in items),
            "walking_distance_m": day_dict.get("walking_distance_m", walking) or 3000,
            "start_time": items[0]["start_time"] if items else "09:00",
            "end_time": items[-1]["end_time"] if items else "18:00",
        }

    responses = None  # lazy init

    def _get_response(self, key: str) -> dict:
        if self.responses is not None:
            return self.responses[key]

        from copy import deepcopy

        # 完整行程数据（带 item_id/day/duration_minutes）
        raw_days = [
            {
                "day": 1, "date": "2026-07-25",
                "items": [
                    {"item_type": "departure", "place_id": "hotel_001",
                     "start_time": "09:00", "end_time": "09:00", "duration_minutes": 0,
                     "note": "从酒店出发", "locked": True},
                    {"item_type": "attraction", "place_id": "attraction_001",
                     "start_time": "09:30", "end_time": "12:00", "duration_minutes": 150,
                     "cost_per_person": 60, "total_cost": 120,
                     "note": "故宫博物院"},
                    {"item_type": "lunch", "place_id": "restaurant_001",
                     "start_time": "12:30", "end_time": "13:30", "duration_minutes": 60,
                     "cost_per_person": 50, "total_cost": 100},
                    {"item_type": "attraction", "place_id": "attraction_002",
                     "start_time": "14:00", "end_time": "16:00", "duration_minutes": 120,
                     "cost_per_person": 30, "total_cost": 60,
                     "note": "天坛公园"},
                    {"item_type": "return", "place_id": "hotel_001",
                     "start_time": "16:30", "end_time": "16:45", "duration_minutes": 15,
                     "note": "返回酒店", "locked": True},
                ]
            },
            {
                "day": 2, "date": "2026-07-26",
                "items": [
                    {"item_type": "departure", "place_id": "hotel_001",
                     "start_time": "09:00", "end_time": "09:00", "duration_minutes": 0,
                     "note": "从酒店出发", "locked": True},
                    {"item_type": "attraction", "place_id": "attraction_003",
                     "start_time": "09:30", "end_time": "11:30", "duration_minutes": 120,
                     "cost_per_person": 20, "total_cost": 40,
                     "note": "颐和园"},
                    {"item_type": "lunch", "place_id": "restaurant_002",
                     "start_time": "12:00", "end_time": "13:00", "duration_minutes": 60,
                     "cost_per_person": 60, "total_cost": 120},
                    {"item_type": "attraction", "place_id": "attraction_004",
                     "start_time": "13:30", "end_time": "15:30", "duration_minutes": 120,
                     "cost_per_person": 0, "total_cost": 0,
                     "note": "国家博物馆"},
                    {"item_type": "return", "place_id": "hotel_001",
                     "start_time": "16:00", "end_time": "16:15", "duration_minutes": 15,
                     "note": "返回酒店", "locked": True},
                ]
            }
        ]
        filled_days = [self._fill_day(d) for d in raw_days]

        self.responses = {
            "planning_preference_interpretation": {
                "daily_themes": ["历史文化探索日", "皇家园林休闲日"],
                "pace_strategy": "normal",
                "combination_rationale": "按地理位置分组，减少跨区移动",
                "priority_order": ["必去景点", "兴趣匹配", "距离就近"],
                "buffer_minutes": 15,
                "rest_strategy": "午餐后安排低强度活动",
                "indoor_outdoor_balance": None,
                "walking_control_strategy": "通过公交替代长距离步行路段",
                "notes": ["第一天集中安排城中心景点"]
            },
            "itinerary_planning": {
                "days": deepcopy(filled_days),
                "total_cost_estimate": 440
            },
            "soft_preference_evaluation": {
                "soft_preference_passed": True,
                "issues": [],
                "overall_assessment": "行程整体合理，符合用户偏好"
            },
            "repair": {
                "days": deepcopy(filled_days),
                "repair_notes": ["Mock 修复：已调整时间避免冲突"]
            },
            "optimize": {
                "days": deepcopy(filled_days),
                "optimization_notes": ["Mock 优化完成"],
                "preference_improvements": ["疲劳度已改善"]
            },
            "local_replan": {
                "days": deepcopy(filled_days),
                "affected_days": [2],
                "replan_notes": ["Mock 局部重规划完成"]
            }
        }
        return self.responses[key]

    def __call__(self, prompt: str) -> str:
        self.call_count += 1
        info(f"LLM 调用 #{self.call_count}")

        # 根据 prompt 内容判断调用类型
        prompt_lower = prompt.lower()
        if "itineraryplanningpolicy" in prompt_lower or "planning_policy" in prompt_lower or "daily_themes" in prompt_lower:
            key = "planning_preference_interpretation"
        elif "soft_preference" in prompt_lower or "软偏好评价" in prompt or "preference_critic" in prompt_lower:
            key = "soft_preference_evaluation"
        elif "hard_constraint_repair" in prompt_lower or "修复" in prompt:
            key = "repair"
        elif "soft_preference_optimization" in prompt_lower or "优化" in prompt:
            key = "optimize"
        elif "local_replan" in prompt_lower or "重规划" in prompt:
            key = "local_replan"
        else:
            key = "itinerary_planning"

        result = self._get_response(key)
        info(f"  -> 返回 {key} (含 {len(result.get('days',[]))} 天行程)")
        return json.dumps(result, ensure_ascii=False)


# ═══════════════════════════════════════════════════
# 2. 真实的 LLM 调用接入示例
# ═══════════════════════════════════════════════════

class OpenAILLM:
    """真实 LLM 调用 — 需要 pip install openai 并配置 API_KEY"""

    def __init__(self, model: str = "gpt-4o-mini"):
        self.model = model
        self._client = None

    def _ensure_client(self):
        if self._client is not None:
            return
        try:
            from openai import OpenAI
        except ImportError:
            warn("需要安装 openai: pip install openai")
            raise
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            warn("请设置环境变量: set OPENAI_API_KEY=sk-xxx")
            raise ValueError("OPENAI_API_KEY 未设置")
        self._client = OpenAI(api_key=api_key)

    def __call__(self, prompt: str) -> str:
        self._ensure_client()
        resp = self._client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )
        return resp.choices[0].message.content


# ═══════════════════════════════════════════════════
# 3. 构建输入数据
# ═══════════════════════════════════════════════════

def build_requirements() -> dict:
    return {
        "session_id": "session_demo_001",
        "city": "北京",
        "start_date": "2026-07-25",
        "days": 2,
        "people": 2,
        "total_budget": 2500,
        "interests": ["历史建筑", "博物馆"],
        "must_visit": ["故宫博物院"],
        "travel_pace": "normal",
        "daily_start_time": "09:00",
        "daily_end_time": "18:00",
        "walking_limit_m": 10000,
        "transport_modes": ["walking", "transit"],
        "original_text": "我们两个人去北京玩两天，喜欢历史建筑，预算2500",
        "food_avoidances": ["辣"],
    }


def build_places() -> list[dict]:
    return [
        # 酒店
        {"place_id": "hotel_001", "name": "北京王府井酒店", "place_type": "hotel",
         "price": 500, "price_type": "per_night", "longitude": 116.41, "latitude": 39.91,
         "city": "北京", "categories": ["酒店"]},
        # 景点
        {"place_id": "attraction_001", "name": "故宫博物院", "place_type": "attraction",
         "price": 60, "price_type": "per_person", "duration_minutes": 180,
         "open_time": "08:30", "close_time": "17:00", "open_weekdays": [1,2,3,4,5,6,7],
         "indoor": False, "categories": ["历史建筑", "博物馆"], "city": "北京",
         "longitude": 116.397, "latitude": 39.916},
        {"place_id": "attraction_002", "name": "天坛公园", "place_type": "attraction",
         "price": 30, "price_type": "per_person", "duration_minutes": 120,
         "open_time": "08:00", "close_time": "18:00", "open_weekdays": [1,2,3,4,5,6,7],
         "indoor": False, "categories": ["历史建筑"], "city": "北京",
         "longitude": 116.407, "latitude": 39.882},
        {"place_id": "attraction_003", "name": "颐和园", "place_type": "attraction",
         "price": 20, "price_type": "per_person", "duration_minutes": 150,
         "open_time": "09:00", "close_time": "17:00", "open_weekdays": [1,2,3,4,5,6,7],
         "indoor": False, "categories": ["皇家园林"], "city": "北京",
         "longitude": 116.275, "latitude": 39.996},
        {"place_id": "attraction_004", "name": "国家博物馆", "place_type": "attraction",
         "price": 0, "price_type": "free", "duration_minutes": 180,
         "open_time": "09:00", "close_time": "17:00", "open_weekdays": [2,3,4,5,6,7],
         "indoor": True, "categories": ["博物馆", "历史"], "city": "北京",
         "longitude": 116.397, "latitude": 39.905},
        # 餐厅
        {"place_id": "restaurant_001", "name": "全聚德烤鸭店", "place_type": "restaurant",
         "price": 100, "price_type": "average_per_person",
         "categories": ["北京菜"], "city": "北京",
         "longitude": 116.397, "latitude": 39.913},
        {"place_id": "restaurant_002", "name": "东来顺涮肉", "place_type": "restaurant",
         "price": 80, "price_type": "average_per_person",
         "categories": ["火锅", "北京菜"], "city": "北京",
         "longitude": 116.41, "latitude": 39.92},
    ]


def build_semantic_preferences() -> list[dict]:
    return [
        {"text": "预算不要太高", "scope": "overall",
         "source_text": "预算2500，希望合理控制费用", "emphasis": "normal"},
        {"text": "喜欢历史建筑", "scope": "attraction",
         "source_text": "喜欢历史建筑", "emphasis": "high"},
    ]


def build_hard_constraints() -> list[dict]:
    return [
        {"field": "total_budget", "operator": "less_than_or_equal",
         "value": 2500, "scope": "overall",
         "source_text": "总预算不能超过2500元"},
    ]


# ═══════════════════════════════════════════════════
# 4. 演示：调用 PlanningAgent
# ═══════════════════════════════════════════════════

def demo_planning_agent(llm):
    h("1. 调用 PlanningAgent — 初始行程规划")

    from agents.planning_agent import PlanningAgent

    agent = PlanningAgent(llm_callable=llm)

    info("准备输入数据...")
    requirements = build_requirements()
    places = build_places()
    semantic_prefs = build_semantic_preferences()
    hard_constraints = build_hard_constraints()

    info("调用 agent.plan()...")
    result = agent.plan(
        requirements=requirements,
        places=places,
        hard_constraints=hard_constraints,
        semantic_preferences=semantic_prefs,
    )

    # 输出结果摘要
    itinerary = result.get("itinerary", {})
    policy = result.get("planning_policy", {})
    budget = result.get("budget", {})
    hard_eval = result.get("hard_evaluation", {})
    soft_eval = result.get("soft_evaluation", {})
    trace = result.get("agent_trace", [])

    print(f"\n  📋 规划策略:")
    print(f"     主题: {policy.get('daily_themes', [])}")
    print(f"     节奏: {policy.get('pace_strategy', '?')}")

    print(f"\n  📅 行程 ({len(itinerary.get('days', []))} 天):")
    for day in itinerary.get("days", []):
        items = day.get("items", [])
        print(f"     第{day['day']}天: {len(items)} 项活动, "
              f"步行{day.get('walking_distance_m', 0)}m, "
              f"费用¥{day.get('daily_cost', 0):.0f}")
        for item in items[:3]:
            print(f"       [{item['start_time']}-{item['end_time']}] "
                  f"{item['item_type']}: {item.get('place_id','?')}")
        if len(items) > 3:
            print(f"       ... 还有 {len(items)-3} 项")

    print(f"\n  💰 预算: ¥{budget.get('total_cost', 0):.0f} / ¥{budget.get('total_budget', 0):.0f}")
    print(f"  ✅ 硬约束: {'通过' if hard_eval.get('passed') else '未通过'} "
          f"({len(hard_eval.get('issues', []))} 项问题)")
    print(f"  😊 软偏好: {'满足' if soft_eval and soft_eval.get('soft_preference_passed') else '待优化'}")

    print(f"\n  📜 Agent 执行轨迹 ({len(trace)} 步):")
    for step in trace:
        print(f"     Step {step['step']}: {step['summary']} ({step['status']})")

    if isinstance(llm, MockLLM):
        print(f"\n  🤖 LLM 调用次数: {llm.call_count}")

    ok("PlanningAgent 调用完成")
    return result


# ═══════════════════════════════════════════════════
# 5. 演示：调用 AdjustmentAgent
# ═══════════════════════════════════════════════════

def demo_adjustment_agent(llm):
    h("2. 调用 AdjustmentAgent — 修改行程")

    from agents.adjustment_agent import AdjustmentAgent
    from schemas.modification import ModificationRequest
    from schemas.itinerary import Itinerary
    from services.version_service import save_version

    # 先保存一个版本
    mock_itinerary = {
        "itinerary_id": "trip_demo_adj_001",
        "session_id": "session_demo_001",
        "version": 1,
        "days": [
            {
                "day": 1, "date": "2026-07-25",
                "items": [
                    {"item_id": "day1_item_000", "day": 1, "item_type": "departure",
                     "place_id": "hotel_001", "start_time": "09:00", "end_time": "09:00",
                     "duration_minutes": 0, "total_cost": 0, "locked": True},
                    {"item_id": "day1_item_001", "day": 1, "item_type": "attraction",
                     "place_id": "attraction_001", "start_time": "09:30", "end_time": "12:00",
                     "duration_minutes": 150, "cost_per_person": 60, "total_cost": 120,
                     "locked": False},
                    {"item_id": "day1_item_002", "day": 1, "item_type": "lunch",
                     "place_id": "restaurant_001", "start_time": "12:30", "end_time": "13:30",
                     "duration_minutes": 60, "cost_per_person": 50, "total_cost": 100,
                     "locked": False},
                ],
                "daily_cost": 220, "walking_distance_m": 3500,
                "start_time": "09:00", "end_time": "13:30",
            }
        ],
        "total_cost": 220,
        "status": "passed",
    }
    save_version(Itinerary(**mock_itinerary))

    # 构造修改请求
    request = ModificationRequest(
        session_id="session_demo_001",
        itinerary_id="trip_demo_adj_001",
        base_version=1,
        target_day=1,
        target_item_id="day1_item_001",
        action="change_to_indoor",
        new_constraints={"indoor": True},
        original_text="第一天改成室内景点",
    )

    def dummy_fetch_alternatives(original_place_id, constraints, limit=5):
        return [
            {"place_id": "attraction_004", "name": "国家博物馆",
             "place_type": "attraction", "indoor": True,
             "price": 0, "categories": ["博物馆", "历史"]},
        ]

    agent = AdjustmentAgent(
        llm_callable=llm,
        alternative_place_fetcher=dummy_fetch_alternatives,
    )

    info("调用 agent.modify()...")
    result = agent.modify(
        request=request,
        requirements=build_requirements(),
        places=build_places(),
    )

    diff = result.get("diff", {})
    trace = result.get("agent_trace", [])

    print(f"\n  📋 修改结果:")
    print(f"     受影响天数: {result.get('affected_days', [])}")

    if diff:
        print(f"     版本: v{diff.get('from_version')} → v{diff.get('to_version')}")
        for c in diff.get("changes", []):
            print(f"     [{c['change_type']}] {c.get('reason', '?')} "
                  f"(费用变动: ¥{c.get('cost_change', 0):.0f})")

    print(f"\n  📜 执行轨迹:")
    for step in trace:
        print(f"     Step {step['step']}: {step['summary']} ({step['status']})")

    ok("AdjustmentAgent 调用完成")


# ═══════════════════════════════════════════════════
# 6. 演示：直接调用 Validator（无需 LLM）
# ═══════════════════════════════════════════════════

def demo_validator_direct():
    h("3. 直接调用 Validator — 批量校验行程（无需 LLM）")

    from validators.hard_constraint_validator import (
        validate_hard_constraints,
        enrich_items_with_places,
    )

    itinerary = {
        "days": [
            {
                "day": 1, "date": "2026-07-25",
                "items": [
                    {"item_id": "i1", "item_type": "attraction", "place_id": "attr_001",
                     "start_time": "09:00", "end_time": "12:00"},
                    {"item_id": "i2", "item_type": "lunch", "place_id": "rest_001",
                     "start_time": "12:30", "end_time": "13:30"},
                ],
                "walking_distance_m": 8500,
            }
        ],
        "total_cost": 3000,
    }
    req = {"total_budget": 2500, "walking_limit_m": 8000, "must_visit": ["故宫"]}

    # 注入 places
    places = [
        {"place_id": "attr_001", "name": "故宫",
         "open_time": "08:30", "close_time": "17:00",
         "open_weekdays": [1,2,3,4,5,6,7], "categories": ["历史"]},
        {"place_id": "rest_001", "name": "餐厅",
         "open_time": "11:00", "close_time": "22:00",
         "categories": ["北京菜"]},
    ]
    enrich_items_with_places(itinerary, places)

    result = validate_hard_constraints(itinerary, req)

    print(f"  硬约束校验: {'通过' if result.passed else '未通过'}")
    for issue in result.issues:
        print(f"    [{issue.severity.value}] [{issue.code}] {issue.message}")

    m = result.metrics
    print(f"\n  指标: 预算匹配={m.budget_match_rate:.0%}, "
          f"必去覆盖率={m.must_visit_coverage_rate:.0%}, "
          f"步行合规={m.walking_limit_valid}")
    ok("直接调用 Validator 成功")


# ═══════════════════════════════════════════════════
# 7. 演示：调用 Budget Service（无需 LLM）
# ═══════════════════════════════════════════════════

def demo_budget_direct():
    h("4. 直接调用 Budget Service — 算预算（无需 LLM）")

    from services.budget_service import calculate_budget

    itinerary = {
        "days": [
            {
                "day": 1,
                "items": [
                    {"item_type": "attraction", "cost_per_person": 60, "total_cost": 120},
                    {"item_type": "lunch", "cost_per_person": 50, "total_cost": 100},
                    {"item_type": "attraction", "cost_per_person": 30, "total_cost": 60},
                ]
            },
            {
                "day": 2,
                "items": [
                    {"item_type": "attraction", "cost_per_person": 20, "total_cost": 40},
                    {"item_type": "lunch", "cost_per_person": 60, "total_cost": 120},
                ]
            }
        ],
        "total_cost": 440,
    }
    req = {"days": 2, "people": 2, "total_budget": 2500}

    budget = calculate_budget(itinerary, req)
    print(f"  酒店: ¥{budget.hotel_cost:.0f}")
    print(f"  门票: ¥{budget.ticket_cost:.0f}")
    print(f"  餐饮: ¥{budget.meal_cost:.0f}")
    print(f"  合计: ¥{budget.total_cost:.0f} / ¥{budget.total_budget:.0f}")
    print(f"  超支: {'是' if budget.over_budget else '否'}")
    ok("Budget Service 直接调用成功")


# ═══════════════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════════════

def main():
    print(f"{B}{C}")
    print(r"     _      _     _        _   _             _   _             ")
    print(r"    / \    | |   | |      | \ | | ___  _   _| \ | | ___  ___   ")
    print(r"   / _ \   | |   | |      |  \| |/ _ \| | | |  \| |/ _ \/ __|  ")
    print(r"  / ___ \  | |___| |___   | |\  | (_) | |_| | |\  |  __/\__ \  ")
    print(r" /_/   \_\ |_____|_____|  |_| \_|\___/ \__,_|_| \_|\___||___/  ")
    print(f"{E}")
    print(f"  Agent 调用演示 — 3 种调用方式\n")

    # ── 选择 LLM ──────────────────────────────────
    use_real_llm = "--llm" in sys.argv

    if use_real_llm:
        try:
            llm = OpenAILLM()
            info("使用真实 LLM (OpenAI)")
        except Exception as e:
            warn(f"真实 LLM 初始化失败: {e}")
            warn("回退到 Mock LLM")
            llm = MockLLM()
    else:
        llm = MockLLM()
        info("使用 Mock LLM (预设数据)")
        if "--llm" not in sys.argv:
            print(f"  {Y}提示: 加 --llm 参数可使用真实 LLM (需设置 OPENAI_API_KEY){E}")

    # ── 无需 LLM 的调用 ───────────────────────────
    demo_validator_direct()
    demo_budget_direct()

    # ── 需 LLM 的调用 ─────────────────────────────
    demo_planning_agent(llm)
    demo_adjustment_agent(llm)

    # ── 总结 ───────────────────────────────────────
    h("总结: 调用方式速查")
    print(f"""
  {B}1. 无需 LLM — 直接调用工具类函数:{E}
     from validators.hard_constraint_validator import validate_hard_constraints
     from services.budget_service import calculate_budget
     from services.version_service import save_version, diff_versions
     from services.diff_service import compute_diff
     from services.itinerary_metrics_service import calculate_day_stats

  {B}2. 需 LLM — 通过 Agent 类:{E}
     from agents.planning_agent import PlanningAgent
     agent = PlanningAgent(llm_callable=your_llm_func)
     result = agent.plan(requirements=..., places=...)

     from agents.adjustment_agent import AdjustmentAgent
     agent = AdjustmentAgent(llm_callable=your_llm_func)
     result = agent.modify(request=..., requirements=...)

  {B}3. 通过 HTTP API:{E}
     POST /api/v1/itineraries/generate      生成初始行程
     POST /api/v1/itineraries/validate      校验行程
     POST /api/v1/itineraries/calculate-budget  算预算
     POST /api/v1/itineraries/modify        修改行程
     GET  /api/v1/itineraries/{{id}}/diff   版本差异
""")

    if isinstance(llm, MockLLM):
        print(f"\n  {Y}当前使用 Mock LLM — Agent 流程已跑通，但不涉及真实推理。{E}")
        print(f"  {Y}加 --llm 参数用真实 LLM 体验完整效果。{E}")


if __name__ == "__main__":
    main()
