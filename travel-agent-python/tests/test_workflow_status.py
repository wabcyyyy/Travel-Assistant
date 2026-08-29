from unittest.mock import patch

from app.agent import tools, workflow
from app.schemas.trip import GenerateRequest
from tests.agent_eval import mock_llm


def _patch_catalog():
    return (
        patch.object(tools, "search_attractions", mock_llm.search_attractions),
        patch.object(tools, "search_foods", mock_llm.search_foods),
        patch.object(tools, "get_consumption", mock_llm.get_consumption),
        patch.object(workflow, "search_hotels", mock_llm.search_hotels),
        patch.object(tools, "attach_poi_images", mock_llm.attach_poi_images),
    )


def test_fallback_generation_is_marked_degraded(monkeypatch):
    monkeypatch.setattr(workflow.settings, "llm_api_key", "")
    monkeypatch.setattr(workflow.settings, "live_price_search", False)
    patches = _patch_catalog()
    for item in patches:
        item.start()
    try:
        response = workflow.run_generate(GenerateRequest(city="杭州", days=1))
    finally:
        for item in reversed(patches):
            item.stop()
    assert response.status == "degraded"
    assert "fallback" in (response.status_reason or "")


def test_valid_llm_generation_is_marked_success(monkeypatch):
    monkeypatch.setattr(workflow.settings, "llm_api_key", "configured")
    monkeypatch.setattr(workflow.settings, "live_price_search", False)

    def valid_generation(*_args, **_kwargs):
        return ([{"day_no": 1, "items": [
            {"item_type": "attraction", "poi_name": "杭州景点1",
             "start_time": "09:00", "end_time": "10:30", "duration_min": 90,
             "cost": 25},
            {"item_type": "food", "poi_name": "杭州本地餐厅1",
             "start_time": "12:00", "end_time": "13:00", "duration_min": 60,
             "cost": 70},
            {"item_type": "hotel", "poi_name": "杭州舒适酒店1", "cost": 350},
        ]}], {"门票": 25})

    patches = _patch_catalog()
    for item in patches:
        item.start()
    with patch.object(workflow, "llm_generate", valid_generation):
        try:
            response = workflow.run_generate(GenerateRequest(city="杭州", days=1))
        finally:
            for item in reversed(patches):
                item.stop()
    assert response.status == "success"
    assert response.status_reason is None


def test_final_validation_marks_unfixed_constraints_as_degraded(monkeypatch):
    monkeypatch.setattr(workflow.settings, "llm_api_key", "configured")
    monkeypatch.setattr(workflow.settings, "live_price_search", False)

    def invalid_generation(*_args, **_kwargs):
        return ([{"day_no": 1, "items": [
            {"item_type": "attraction", "poi_name": "杭州景点1",
             "start_time": "17:00", "end_time": "19:00", "duration_min": 120,
             "cost": 25},
        ]}], {"门票": 25})

    patches = _patch_catalog()
    for item in patches:
        item.start()
    with patch.object(workflow, "llm_generate", invalid_generation):
        try:
            response = workflow.run_generate(GenerateRequest(city="杭州", days=1))
        finally:
            for item in reversed(patches):
                item.stop()
    assert response.status == "degraded"
    assert "行程约束问题" in (response.status_reason or "")
    assert any("开放时间不符" in entry for entry in response.validation_log)
