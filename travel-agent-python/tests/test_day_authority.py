import pytest

from app.agent.day_stream import _canonicalize_known_plan


def _poi(name="西湖", category="attraction", price=0):
    return {
        "id": 1,
        "name": name,
        "category": category,
        "address": "杭州西湖区",
        "latitude": 30.24,
        "longitude": 120.14,
        "ticket_price": price,
        "duration_min": 120,
        "open_time": "全天开放",
        "tags": "自然",
    }


def test_unknown_poi_is_rejected_even_when_prompt_allowed_it():
    with pytest.raises(ValueError, match="白名单"):
        _canonicalize_known_plan(
            {"items": [{"item_type": "attraction", "poi_name": "模型编造景点", "cost": 1}]},
            [_poi()], [], [],
        )


def test_authority_fields_replace_model_values():
    result = _canonicalize_known_plan(
        {"items": [{
            "item_type": "attraction", "poi_name": "西湖", "cost": 9999,
            "latitude": 0, "longitude": 0, "duration_min": 1,
        }]},
        [_poi(price=35)], [], [],
    )
    item = result["items"][0]
    assert item["cost"] == 35
    assert item["latitude"] == 30.24
    assert item["longitude"] == 120.14
    assert item["duration_min"] == 120
    assert item["open_time"] == "全天开放"


def test_transport_is_a_synthetic_item_and_does_not_require_poi():
    result = _canonicalize_known_plan(
        {"items": [{"item_type": "transport", "poi_name": "地铁接驳"}]},
        [], [], [],
    )
    assert result["items"][0]["item_type"] == "transport"
