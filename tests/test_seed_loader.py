from backend.app.database.seed_loader import (
    get_resource_counts,
    load_all_resources,
    load_hotels,
    load_places,
    load_restaurants,
)
from backend.app.schemas import Place


def test_load_places_from_sample_data() -> None:
    places = load_places()

    assert len(places) == 3
    assert all(isinstance(place, Place) for place in places)
    assert all(place.place_type == "attraction" for place in places)


def test_load_hotels_from_sample_data() -> None:
    hotels = load_hotels()

    assert len(hotels) == 2
    assert all(isinstance(hotel, Place) for hotel in hotels)
    assert all(hotel.place_type == "hotel" for hotel in hotels)


def test_load_restaurants_from_sample_data() -> None:
    restaurants = load_restaurants()

    assert len(restaurants) == 2
    assert all(isinstance(restaurant, Place) for restaurant in restaurants)
    assert all(restaurant.place_type == "restaurant" for restaurant in restaurants)


def test_load_all_resources_from_sample_data() -> None:
    resources = load_all_resources()

    assert set(resources) == {"景点", "酒店", "餐厅"}
    assert len(resources["景点"]) == 3
    assert len(resources["酒店"]) == 2
    assert len(resources["餐厅"]) == 2


def test_get_resource_counts_from_sample_data() -> None:
    counts = get_resource_counts()

    assert counts == {
        "景点": 3,
        "酒店": 2,
        "餐厅": 2,
        "总计": 7,
    }
