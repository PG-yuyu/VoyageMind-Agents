import pytest

from backend.app.tools.candidate_search_tool import search_candidates


def test_search_candidates_by_city() -> None:
    results = search_candidates(city="北京")

    assert len(results) == 7
    assert all(place.city == "北京" for place in results)


def test_search_candidates_by_type() -> None:
    results = search_candidates(place_type="hotel")

    assert len(results) == 2
    assert all(place.place_type == "hotel" for place in results)


def test_search_candidates_by_tags() -> None:
    results = search_candidates(tags=["历史文化"])

    assert [place.name for place in results] == ["故宫博物院"]


def test_search_candidates_by_price_range() -> None:
    results = search_candidates(min_price=30, max_price=80)

    assert results
    assert all(place.price is not None for place in results)
    assert all(30 <= place.price <= 80 for place in results if place.price is not None)


def test_search_candidates_with_combined_conditions() -> None:
    results = search_candidates(
        city="北京",
        place_type="attraction",
        area="东城区",
        tags=["历史文化"],
    )

    assert [place.name for place in results] == ["故宫博物院"]


def test_search_candidates_without_match_returns_empty_list() -> None:
    results = search_candidates(city="上海")

    assert results == []


def test_search_candidates_rejects_invalid_place_type() -> None:
    with pytest.raises(ValueError):
        search_candidates(place_type="shopping")
