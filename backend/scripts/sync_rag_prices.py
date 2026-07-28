"""
从 RAG 文档同步价格到种子 JSON 数据
===================================

遍历 LangChain_RAG/docs/tianjin/ 下所有地点文档，
提取「地点编号」和「参考价格」，解析为数值，
更新 data/*.json 中对应条目的 price 字段。

用法:
    python backend/scripts/sync_rag_prices.py          # 执行同步
    python backend/scripts/sync_rag_prices.py --dry-run # 仅预览
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


# ── 路径配置 ──────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAG_DIR = PROJECT_ROOT / "LangChain_RAG" / "docs" / "tianjin"
DATA_DIR = PROJECT_ROOT / "data"

# JSON 文件名 → RAG 子目录
TYPE_MAPPING = {
    "places.json": "attractions",
    "hotels.json": "hotels",
    "restaurants.json": "restaurants",
}


# ── 价格解析 ──────────────────────────────────────────────────────────


def parse_price(raw: str) -> float | None:
    """从 RAG 文档的「参考价格」文本中提取数值。

    支持的格式:
      - "免费"                   → 0
      - "76元/人"               → 76
      - "1203元/间夜起"          → 1203
      - "847元/间夜起（含早）"    → 847
      - 无法解析                 → None（不更新）
    """
    if not raw or not raw.strip():
        return None

    text = raw.strip()

    # "免费" → 0
    if "免费" in text:
        return 0.0

    # 提取第一个连续数字
    m = re.search(r"(\d+)", text)
    if m:
        return float(m.group(1))

    return None


# ── RAG 文档解析 ──────────────────────────────────────────────────────


def extract_rag_prices(rag_dir: Path) -> dict[str, float]:
    """遍历 RAG 文档目录，提取 place_id → price 映射。

    Returns:
        dict[place_id, price]: 从 RAG 文档中解析出的价格
    """
    prices: dict[str, float] = {}
    file_count = 0
    skip_count = 0

    for subdir in TYPE_MAPPING.values():
        d = rag_dir / subdir
        if not d.is_dir():
            print(f"  [WARN] 目录不存在: {d}")
            continue

        for fname in sorted(os.listdir(d)):
            if not fname.endswith(".txt"):
                continue

            filepath = d / fname
            content = filepath.read_text(encoding="utf-8")

            # 提取 地点编号
            m_id = re.search(r"地点编号[：:]\s*(\S+)", content)
            if not m_id:
                print(f"  [WARN] {fname}: 未找到地点编号，跳过")
                skip_count += 1
                continue
            place_id = m_id.group(1).strip()

            # 提取 参考价格
            m_price = re.search(r"参考价格[：:]\s*(.+)$", content, re.MULTILINE)
            if not m_price:
                print(f"  [WARN] {fname} ({place_id}): 未找到参考价格，跳过")
                skip_count += 1
                continue
            raw_price = m_price.group(1).strip()

            price = parse_price(raw_price)
            if price is None:
                print(f"  [WARN] {fname} ({place_id}): 无法解析价格 \"{raw_price}\"，跳过")
                skip_count += 1
                continue

            prices[place_id] = price
            file_count += 1

    print(f"  解析完成: {file_count} 个价格, {skip_count} 个跳过")
    return prices


# ── JSON 更新 ─────────────────────────────────────────────────────────


def update_json_file(
    filepath: Path,
    rag_prices: dict[str, float],
    dry_run: bool = False,
) -> dict[str, Any]:
    """读取 JSON 文件，更新匹配条目的 price 字段，写回。

    Returns:
        dict: {place_id: (old_price, new_price)} 变更记录
    """
    with open(filepath, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    changes: dict[str, tuple] = {}
    updated = 0

    for entry in data:
        pid = entry.get("place_id", "")
        if pid not in rag_prices:
            continue

        new_price = rag_prices[pid]
        old_price = entry.get("price")

        # 判断是否需要更新：旧值为 None/0 或与新值不同
        if old_price == new_price:
            continue

        entry["price"] = new_price
        changes[pid] = (old_price, new_price)
        updated += 1

    if updated > 0 and not dry_run:
        with open(filepath, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.write("\n")  # 文件末尾换行

    return {"updated": updated, "changes": changes}


# ── 主流程 ────────────────────────────────────────────────────────────


def main(dry_run: bool = False) -> None:
    """主入口。"""
    mode = "[预览模式 --dry-run]" if dry_run else "[执行模式]"
    print(f"\n{'='*60}")
    print(f"  RAG 价格同步脚本 {mode}")
    print(f"  运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")

    # 1. 从 RAG 文档提取价格
    print("[1/3] 从 RAG 文档提取价格...")
    rag_prices = extract_rag_prices(RAG_DIR)
    if not rag_prices:
        print("  [FAIL] 未提取到任何价格，终止")
        sys.exit(1)

    # 2. 更新 JSON 文件
    print(f"\n[2/3] 更新 JSON 种子文件...")
    total_updated = 0
    all_changes: dict[str, dict] = {}

    for json_file, _subdir in TYPE_MAPPING.items():
        filepath = DATA_DIR / json_file
        if not filepath.exists():
            print(f"  [WARN] 文件不存在: {filepath}")
            continue

        result = update_json_file(filepath, rag_prices, dry_run=dry_run)
        n = result["updated"]
        changes = result["changes"]
        total_updated += n
        all_changes[json_file] = changes

        if dry_run:
            print(f"\n  [FILE] {json_file}: {n} 条待更新")
        else:
            print(f"  [OK] {json_file}: {n} 条已更新")

        for pid, (old, new) in changes.items():
            print(f"      {pid}: {old} → {new}")

    # 3. 汇总
    print(f"\n[3/3] 汇总")
    if total_updated == 0:
        print("  [OK] 所有价格已是最新，无需更新")
    elif dry_run:
        print(f"  [INFO] 共 {total_updated} 条待更新（运行不带 --dry-run 执行）")
    else:
        print(f"  [OK] 共更新 {total_updated} 条价格记录")

    # 检查未被 RAG 覆盖的 JSON 条目
    print(f"\n  覆盖情况:")
    for json_file in TYPE_MAPPING:
        filepath = DATA_DIR / json_file
        if not filepath.exists():
            continue
        with open(filepath, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        missing = [d["place_id"] for d in data if d["place_id"] not in rag_prices]
        if missing:
            print(f"    {json_file}: {len(missing)} 条无 RAG 文档 → 保持原值 ({', '.join(missing)})")
        else:
            print(f"    {json_file}: 全部覆盖 ({len(data)} 条)")

    print(f"\n{'='*60}")
    print(f"  同步{'预览' if dry_run else ''}完成")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    main(dry_run=dry_run)
