"""
使用 DeepSeek 驱动 PlanningAgent — 端到端行程规划
=====================================================

运行前:
  1. 设置 API Key:  set DEEPSEEK_API_KEY=sk-xxx
  2. 运行:          python run_with_deepseek.py

流程:
  用户需求 → DeepSeek 理解偏好 → DeepSeek 生成行程
  → Python 硬约束校验 → DeepSeek 软偏好评价 → 输出结果
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent
os.chdir(ROOT)

# Windows UTF-8 兼容
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


# ── 颜色 ──────────────────────────────────────────
C = "\033[96m"; G = "\033[92m"; Y = "\033[93m"; R = "\033[91m"; B = "\033[1m"; E = "\033[0m"

def h(t): print(f"\n{B}{'='*60}{E}\n{B}{t}{E}\n{B}{'='*60}{E}")
def ok(m): print(f"  {G}[OK]{E} {m}")
def info(m): print(f"  {C}[..]{E} {m}")
def warn(m): print(f"  {Y}[!]{E} {m}")


def build_requirements() -> dict:
    return {
        "session_id": "session_deepseek_001",
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
        "original_text": "我们两个人去北京玩两天，喜欢历史建筑和博物馆，预算2500元，故宫必须去",
        "food_avoidances": ["辣"],
    }


def build_places() -> list[dict]:
    return [
        # 酒店
        {"place_id": "hotel_001", "name": "北京王府井酒店", "place_type": "hotel",
         "price": 500, "price_type": "per_night", "longitude": 116.41, "latitude": 39.91,
         "city": "北京", "categories": ["酒店"], "open_time": "00:00", "close_time": "24:00"},
        # 景点
        {"place_id": "attraction_001", "name": "故宫博物院", "place_type": "attraction",
         "price": 60, "price_type": "per_person", "duration_minutes": 180,
         "open_time": "08:30", "close_time": "17:00", "open_weekdays": [1,2,3,4,5,6,7],
         "indoor": False, "categories": ["历史建筑", "博物馆"], "city": "北京",
         "longitude": 116.397, "latitude": 39.916},
        {"place_id": "attraction_002", "name": "天坛公园", "place_type": "attraction",
         "price": 30, "price_type": "per_person", "duration_minutes": 120,
         "open_time": "08:00", "close_time": "18:00", "open_weekdays": [1,2,3,4,5,6,7],
         "indoor": False, "categories": ["历史建筑", "世界遗产"], "city": "北京",
         "longitude": 116.407, "latitude": 39.882},
        {"place_id": "attraction_003", "name": "颐和园", "place_type": "attraction",
         "price": 20, "price_type": "per_person", "duration_minutes": 150,
         "open_time": "06:30", "close_time": "18:00", "open_weekdays": [1,2,3,4,5,6,7],
         "indoor": False, "categories": ["皇家园林", "世界遗产"], "city": "北京",
         "longitude": 116.275, "latitude": 39.996},
        {"place_id": "attraction_004", "name": "中国国家博物馆", "place_type": "attraction",
         "price": 0, "price_type": "free", "duration_minutes": 180,
         "open_time": "09:00", "close_time": "17:00", "open_weekdays": [2,3,4,5,6,7],
         "indoor": True, "categories": ["博物馆", "历史", "艺术"], "city": "北京",
         "longitude": 116.397, "latitude": 39.905},
        {"place_id": "attraction_005", "name": "北海公园", "place_type": "attraction",
         "price": 10, "price_type": "per_person", "duration_minutes": 90,
         "open_time": "06:30", "close_time": "20:00", "open_weekdays": [1,2,3,4,5,6,7],
         "indoor": False, "categories": ["皇家园林", "公园"], "city": "北京",
         "longitude": 116.389, "latitude": 39.925},
        # 餐厅
        {"place_id": "restaurant_001", "name": "全聚德烤鸭（前门店）", "place_type": "restaurant",
         "price": 120, "price_type": "average_per_person",
         "categories": ["北京菜", "烤鸭"], "city": "北京",
         "longitude": 116.397, "latitude": 39.896, "open_time": "10:30", "close_time": "21:00"},
        {"place_id": "restaurant_002", "name": "东来顺饭庄（王府井店）", "place_type": "restaurant",
         "price": 100, "price_type": "average_per_person",
         "categories": ["火锅", "北京菜", "清真"], "city": "北京",
         "longitude": 116.410, "latitude": 39.915, "open_time": "11:00", "close_time": "22:00"},
        {"place_id": "restaurant_003", "name": "护国寺小吃", "place_type": "restaurant",
         "price": 30, "price_type": "average_per_person",
         "categories": ["小吃", "北京菜", "清真"], "city": "北京",
         "longitude": 116.378, "latitude": 39.933, "open_time": "06:00", "close_time": "21:00"},
    ]


def build_semantic_preferences() -> list[dict]:
    return [
        {"text": "预算不要太高", "scope": "overall",
         "source_text": "预算2500元，希望合理控制费用", "emphasis": "normal"},
        {"text": "喜欢历史建筑和博物馆", "scope": "attraction",
         "source_text": "喜欢历史建筑和博物馆", "emphasis": "high"},
    ]


# ═══════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════

def main():
    print(f"{B}{C}")
    print(r"   ____  _____    _    ______ _  __ _____ _____ _  ________ ")
    print(r"  |  _ \| ____|  / \  |  _  | |/ /|  ___|  ___| |/ /  ___|")
    print(r"  | | | |  _|   / _ \ | | | | ' / | |_  | |__ | ' /| |__  ")
    print(r"  | |_| | |___ / ___ \| |_| | . \ |  _| |  __|| . \\___ \ ")
    print(r"  |____/|_____/_/   \_\____/|_|\_\|_|   |_|   |_|\_\___/  ")
    print(f"{E}")
    print(f"  DeepSeek × PlanningAgent — 智能行程规划")
    print()

    # ── 1. 初始化 DeepSeek LLM ─────────────────────
    h("1. 初始化 DeepSeek LLM")
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        warn("未设置 DEEPSEEK_API_KEY 环境变量")
        print(f"\n  {Y}请设置 API Key:{E}")
        print(f"    set DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxx")
        print(f"\n  {Y}或者在代码中传入:{E}")
        print(f"    llm = DeepSeekLLM(api_key='sk-xxx')")
        sys.exit(1)

    try:
        from clients.deepseek_llm import DeepSeekLLM
        llm = DeepSeekLLM(
            api_key='sk-0e8db86491ee4be0ac3eafe08ffff107',
            model="deepseek-chat",  # 或 deepseek-reasoner
            temperature=0.3,
        )
        ok(f"DeepSeek 连接成功 (model={llm.model})")
    except Exception as e:
        fail(f"DeepSeek 初始化失败: {e}")
        sys.exit(1)

    # ── 2. 调用 PlanningAgent ──────────────────────
    h("2. 调用 PlanningAgent — DeepSeek 正在规划行程...")
    from agents.planning_agent import PlanningAgent

    agent = PlanningAgent(llm_callable=llm)

    info(f"城市: 北京 | 天数: 2 | 预算: ¥2500 | 兴趣: 历史建筑/博物馆")
    info(f"必去: 故宫博物院 | 人数: 2")
    print()

    result = agent.plan(
        requirements=build_requirements(),
        places=build_places(),
        semantic_preferences=build_semantic_preferences(),
    )

    # ── 3. 输出结果 ─────────────────────────────────
    h("3. 规划结果")

    itinerary = result.get("itinerary", {})
    policy = result.get("planning_policy", {})
    budget = result.get("budget", {})
    hard_eval = result.get("hard_evaluation", {})
    soft_eval = result.get("soft_evaluation", {})
    trace = result.get("agent_trace", [])
    phase = result.get("phase", "")

    # 规划策略
    print(f"\n  {B}规划策略:{E}")
    print(f"    每日主题: {policy.get('daily_themes', [])}")
    print(f"    节奏: {policy.get('pace_strategy', '?')}")
    print(f"    组合逻辑: {policy.get('combination_rationale', '?')}")

    # 每日行程
    print(f"\n  {B}每日行程:{E}")
    for day in itinerary.get("days", []):
        print(f"\n  ┌─ {B}第{day['day']}天{E} ({day.get('date', '')}) "
              f"— 步行{day.get('walking_distance_m', 0)}m "
              f"| 费用¥{day.get('daily_cost', 0):.0f}")
        for item in day.get("items", []):
            icon = {"departure": "🏨", "attraction": "🏛️", "lunch": "🍜",
                    "dinner": "🍽️", "return": "🏨", "transport": "🚌",
                    "rest": "☕", "hotel": "🏨"}.get(item.get("item_type", ""), "•")
            note = item.get("note", "")
            note_str = f" — {note}" if note else ""
            print(f"  │ {icon} [{item['start_time']}-{item['end_time']}] "
                  f"{item.get('item_type', '?')}: {item.get('place_id', '?')}{note_str}")
        print(f"  └─")

    # 预算
    print(f"\n  {B}预算:{E}")
    print(f"    酒店: ¥{budget.get('hotel_cost', 0):.0f}  | "
          f"门票: ¥{budget.get('ticket_cost', 0):.0f}  | "
          f"餐饮: ¥{budget.get('meal_cost', 0):.0f}  | "
          f"交通: ¥{budget.get('transport_cost', 0):.0f}")
    print(f"    ───────────────────────────────────")
    print(f"    合计: ¥{budget.get('total_cost', 0):.0f}  /  "
          f"预算: ¥{budget.get('total_budget', 0):.0f}  /  "
          f"剩余: ¥{budget.get('remaining_budget', 0):.0f}")
    budget_status = "✅ 预算内" if not budget.get("over_budget") else "❌ 超预算"
    print(f"    状态: {budget_status}")

    # 校验
    print(f"\n  {B}硬约束校验:{E}  "
          f"{'✅ 通过' if hard_eval.get('passed') else '❌ 未通过'} "
          f"({len(hard_eval.get('issues', []))} 项问题)")
    for issue in hard_eval.get("issues", []):
        print(f"    [{issue.get('severity','')}] {issue.get('message','')}")
        if issue.get("suggestion"):
            print(f"      💡 {issue['suggestion']}")

    m = hard_eval.get("metrics", {})
    print(f"\n    预算匹配: {m.get('budget_match_rate', 0)*100:.0f}%  |  "
          f"必去覆盖: {m.get('must_visit_coverage_rate', 0)*100:.0f}%  |  "
          f"兴趣覆盖: {m.get('interest_coverage_rate', 0)*100:.0f}%")

    # 软偏好
    print(f"\n  {B}软偏好评价:{E}  "
          f"{'😊 满足' if soft_eval and soft_eval.get('soft_preference_passed') else '🤔 待优化'}")
    if soft_eval and soft_eval.get("overall_assessment"):
        print(f"    {soft_eval['overall_assessment']}")

    # Agent 轨迹
    print(f"\n  {B}Agent 执行轨迹 ({len(trace)} 步):{E}")
    for step in trace:
        status_icon = "✅" if step.get("status") == "success" else "⏳"
        print(f"    {status_icon} Step {step['step']}: {step.get('summary', step.get('action', '?'))}")

    # ── 总结 ────────────────────────────────────────
    h("✅ 验证完成")
    print(f"\n  最终状态: {phase}")
    print(f"  LLM: DeepSeek ({llm.model})")
    print(f"  总费用: ¥{budget.get('total_cost', 0):.0f}")
    print(f"\n  你可以查看 demo_report.html 获取可视化报告")
    print(f"  或访问 http://localhost:8000/docs 测试 API")


if __name__ == "__main__":
    main()
