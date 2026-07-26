"""旅游资源查询服务测试。"""

import unittest


class PlaceSearchServiceTest(unittest.TestCase):
    """旅游资源查询服务验收测试。"""

    def test_service_can_filter_by_basic_fields(self) -> None:
        """服务可以按城市、类型、区域、标签和价格筛选资源。"""

        from backend.app.services import PlaceSearchQuery, PlaceSearchService

        service = PlaceSearchService()

        beijing_results = service.search(PlaceSearchQuery(city="北京"))
        tianjin_results = service.search(PlaceSearchQuery(city="天津"))
        attractions = service.search(PlaceSearchQuery(place_type="attraction"))
        east_results = service.search(PlaceSearchQuery(area="东城区"))
        culture_results = service.search(PlaceSearchQuery(tags=["历史文化"]))
        cheap_results = service.search(PlaceSearchQuery(max_price=50))

        self.assertEqual(len(beijing_results), 7)
        self.assertGreaterEqual(len(tianjin_results), 10)
        self.assertGreaterEqual(len(attractions), 8)
        self.assertGreaterEqual(len(east_results), 1)
        self.assertIn("故宫博物院", [place.name for place in culture_results])
        self.assertIn("天津古文化街", [place.name for place in culture_results])
        self.assertTrue(all(place.price <= 50 for place in cheap_results))

    def test_service_can_filter_tianjin_resources(self) -> None:
        """服务可以按天津城市和本地偏好筛选成员二联调用资源。"""

        from backend.app.services import PlaceSearchQuery, PlaceSearchService

        service = PlaceSearchService()

        culture_attractions = service.search(
            PlaceSearchQuery(
                city="天津",
                place_type="attraction",
                tags=["历史文化"],
            )
        )
        convenient_hotels = service.search(
            PlaceSearchQuery(
                city="天津",
                place_type="hotel",
                tags=["交通方便"],
                max_price=600,
            )
        )
        local_restaurants = service.search(
            PlaceSearchQuery(
                city="天津",
                place_type="restaurant",
                tags=["本地风味"],
                max_price=120,
            )
        )

        self.assertGreaterEqual(len(culture_attractions), 1)
        self.assertGreaterEqual(len(convenient_hotels), 1)
        self.assertGreaterEqual(len(local_restaurants), 1)
        self.assertTrue(all(place.city == "天津" for place in culture_attractions))
        self.assertTrue(all(place.city == "天津" for place in convenient_hotels))
        self.assertTrue(all(place.city == "天津" for place in local_restaurants))

    def test_service_can_filter_by_people_and_limit(self) -> None:
        """服务可以按适合人群筛选并限制返回数量。"""

        from backend.app.services import PlaceSearchQuery, PlaceSearchService

        service = PlaceSearchService()

        student_results = service.search(PlaceSearchQuery(suitable_for=["学生"]))
        limited_results = service.search(PlaceSearchQuery(city="北京", limit=1))

        self.assertGreaterEqual(len(student_results), 1)
        self.assertEqual(len(limited_results), 1)

    def test_special_search_methods_return_expected_types(self) -> None:
        """专用查询方法只返回对应类型资源。"""

        from backend.app.services import PlaceSearchService

        service = PlaceSearchService()

        self.assertTrue(
            all(
                place.place_type == "attraction"
                for place in service.search_attractions()
            )
        )
        self.assertTrue(
            all(place.place_type == "hotel" for place in service.search_hotels())
        )
        self.assertTrue(
            all(
                place.place_type == "restaurant"
                for place in service.search_restaurants()
            )
        )


if __name__ == "__main__":
    unittest.main()
