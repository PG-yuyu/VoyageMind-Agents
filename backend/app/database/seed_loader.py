"""旅游资源样例数据读取工具。"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    backend_root = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(backend_root))
    from backend.app.schemas import Place
else:
    from ..schemas import Place


DEFAULT_DATA_DIR = Path(__file__).resolve().parents[3] / "data"
RESOURCE_FILES = {
    "景点": "places.json",
    "酒店": "hotels.json",
    "餐厅": "restaurants.json",
}


def read_json_list(file_path: Path) -> list[dict[str, Any]]:
    """读取 JSON 数组文件。"""

    if not file_path.exists():
        raise FileNotFoundError(f"样例数据文件不存在：{file_path}")

    with file_path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, list):
        raise ValueError(f"样例数据文件必须是数组：{file_path}")

    return data


def load_resource_file(
    file_name: str, data_dir: Path = DEFAULT_DATA_DIR
) -> list[Place]:
    """读取单个资源文件并转换为地点模型。"""

    file_path = data_dir / file_name
    return [Place.from_dict(item) for item in read_json_list(file_path)]


def load_places(data_dir: Path = DEFAULT_DATA_DIR) -> list[Place]:
    """读取景点样例数据。"""

    return load_resource_file("places.json", data_dir)


def load_hotels(data_dir: Path = DEFAULT_DATA_DIR) -> list[Place]:
    """读取酒店样例数据。"""

    return load_resource_file("hotels.json", data_dir)


def load_restaurants(data_dir: Path = DEFAULT_DATA_DIR) -> list[Place]:
    """读取餐厅样例数据。"""

    return load_resource_file("restaurants.json", data_dir)


def load_all_resources(data_dir: Path = DEFAULT_DATA_DIR) -> dict[str, list[Place]]:
    """读取全部旅游资源样例数据。"""

    return {
        "景点": load_places(data_dir),
        "酒店": load_hotels(data_dir),
        "餐厅": load_restaurants(data_dir),
    }


def get_resource_counts(data_dir: Path = DEFAULT_DATA_DIR) -> dict[str, int]:
    """统计三类旅游资源数量。"""

    resources = load_all_resources(data_dir)
    counts = {resource_type: len(items) for resource_type, items in resources.items()}
    counts["总计"] = sum(counts.values())
    return counts


def print_resource_counts(data_dir: Path = DEFAULT_DATA_DIR) -> None:
    """打印样例数据资源数量。"""

    counts = get_resource_counts(data_dir)
    for resource_type in ["景点", "酒店", "餐厅", "总计"]:
        print(f"{resource_type}数量：{counts[resource_type]}")


def main() -> None:
    """命令行入口：读取样例数据并打印数量。"""

    print_resource_counts()


if __name__ == "__main__":
    main()
