"""旅游资源仓库层测试。"""

import sys
import unittest
from pathlib import Path

backend_root = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(backend_root))


class PlaceRepositoryTest(unittest.TestCase):
    """旅游资源仓库层验收测试。"""

    def test_repository_can_list_resources(self) -> None:
        """仓库可以分别列出景点、酒店、餐厅和全部资源。"""

        from backend.app.repositories import PlaceRepository

        repository = PlaceRepository()

        self.assertGreaterEqual(len(repository.list_attractions()), 8)
        self.assertGreaterEqual(len(repository.list_hotels()), 4)
        self.assertGreaterEqual(len(repository.list_restaurants()), 5)
        self.assertGreaterEqual(len(repository.list_all()), 17)

    def test_repository_can_list_by_type(self) -> None:
        """仓库可以按资源类型列出候选资源。"""

        from backend.app.repositories import PlaceRepository

        repository = PlaceRepository()

        self.assertGreaterEqual(len(repository.list_by_type("attraction")), 8)
        self.assertGreaterEqual(len(repository.list_by_type("hotel")), 4)
        self.assertGreaterEqual(len(repository.list_by_type("restaurant")), 5)

        with self.assertRaises(ValueError):
            repository.list_by_type("shopping")

    def test_repository_can_get_by_id(self) -> None:
        """仓库可以按地点编号查找资源。"""

        from backend.app.repositories import PlaceRepository

        repository = PlaceRepository()

        self.assertEqual(repository.get_by_id("place_001").name, "故宫博物院")
        self.assertIsNone(repository.get_by_id("not_exists"))


if __name__ == "__main__":
    unittest.main()
