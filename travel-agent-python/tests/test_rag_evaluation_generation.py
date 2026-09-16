"""P1 引用式生成与 RAGAS 风格评测的离线测试。

覆盖：ReferencePool 收集/编号/匹配/统计、引用落地字段覆盖、开放模式
Prompt 注入、单日生成引用落地集成、生成评测指标与聚合。
全部离线：LLM 客户端与高德均以替身注入。
"""

import json

from app.agent import day_stream
from app.agent.reference_pool import (
    ReferencePool,
    normalize_poi_name,
)
from app.rag import evaluation_generation as eg
from app.schemas.trip import GenerateDayRequest


def _poi(
    name="西湖风景名胜区", category="attraction", price=0, pid=1, source="mysql.poi_knowledge", updated="2026-09-01"
):
    return {
        "id": pid,
        "name": name,
        "category": category,
        "address": f"{name}地址",
        "latitude": 30.24,
        "longitude": 120.14,
        "ticket_price": price,
        "duration_min": 120,
        "open_time": "全天开放",
        "tags": "自然",
        "source": source,
        "source_updated_at": updated,
    }


def _context():
    return {
        "candidates": [_poi(), _poi("雷峰塔", price=40, pid=2)],
        "foods": [_poi("楼外楼", category="food", price=120, pid=3)],
        "hotels": [_poi("西湖国宾馆", category="hotel", price=2000, pid=4)],
    }


# ---------- ReferencePool ----------


def test_reference_pool_collects_and_numbers():
    pool = ReferencePool(_context())
    assert len(pool) == 4
    block = pool.block()
    assert "[R1] 西湖风景名胜区｜attraction｜票价0｜全天开放" in block
    assert "[R3] 楼外楼｜food" in block
    assert "[R4] 西湖国宾馆｜hotel" in block
    assert "refs" in block  # 引用指令注入


def test_reference_pool_empty_context_block_is_blank():
    pool = ReferencePool({})
    assert len(pool) == 0
    assert pool.block() == ""


def test_reference_pool_caps_collection():
    context = {
        "candidates": [_poi(f"景点{index}", pid=index) for index in range(30)],
        "foods": [_poi(f"餐厅{index}", category="food", pid=100 + index) for index in range(20)],
        "hotels": [_poi(f"酒店{index}", category="hotel", pid=200 + index) for index in range(10)],
    }
    pool = ReferencePool(context)
    assert len(pool) == 16 + 6 + 4


def test_normalize_poi_name_strips_variants():
    assert normalize_poi_name(" 西湖（主园区）·一 ") == "西湖主园区一"


# ---------- 引用落地 ----------


def test_ground_by_name_overrides_authority_fields():
    pool = ReferencePool(_context())
    item = {
        "item_type": "attraction",
        "poi_name": "西湖风景名胜区",
        "cost": 9999,
        "latitude": 0,
        "longitude": 0,
        "refs": [1],
    }
    assert pool.ground(item) is True
    assert item["cost"] == 0
    assert item["latitude"] == 30.24
    assert item["open_time"] == "全天开放"
    assert item["source"] == "mysql.poi_knowledge"
    assert item["verification_status"] == "partially_verified"
    assert item["value_kind"] == "observed"
    assert "refs" not in item  # 中间产物已移除
    assert pool.stats["grounded"] == 1
    assert pool.stats["items"] == 1


def test_ground_by_refs_normalizes_model_abbreviation():
    pool = ReferencePool(_context())
    item = {"item_type": "attraction", "poi_name": "西湖", "refs": [2]}
    assert pool.ground(item) is True
    assert item["poi_name"] == "雷峰塔"  # 名称归一为权威名
    assert item["cost"] == 40
    assert item["poi_id"] == "2"
    assert pool.stats["refs_cited"] == 1
    assert pool.stats["refs_valid"] == 1


def test_ground_unmatched_item_keeps_open_semantics():
    pool = ReferencePool(_context())
    item = {"item_type": "attraction", "poi_name": "模型自选景点", "cost": 88}
    assert pool.ground(item) is False
    assert item["cost"] == 88
    assert "source" not in item
    assert pool.stats["grounded"] == 0


def test_ground_transport_and_empty_items_are_skipped():
    pool = ReferencePool(_context())
    transport = {"item_type": "transport", "poi_name": "地铁接驳"}
    assert pool.ground(transport) is False
    assert pool.stats["items"] == 0


def test_ground_invalid_refs_do_not_crash():
    pool = ReferencePool(_context())
    item = {"item_type": "attraction", "poi_name": "模型自选", "refs": [99, "x", True]}
    assert pool.ground(item) is False
    assert pool.stats["refs_cited"] == 1
    assert pool.stats["refs_valid"] == 0


def test_ground_tracks_context_utilization():
    pool = ReferencePool(_context())
    pool.ground({"item_type": "attraction", "poi_name": "西湖风景名胜区"})
    pool.ground({"item_type": "attraction", "poi_name": "雷峰塔", "refs": [2]})
    assert pool.stats["cited_references"] == 2
    assert pool.stats["references"] == 4


# ---------- 开放模式 Prompt 注入 ----------


class _FakeLLM:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def complete(self, user_prompt, system_prompt="", **_kwargs):
        self.calls.append({"user": user_prompt, "system": system_prompt})
        return json.dumps(self.payload, ensure_ascii=False)


def test_open_day_prompt_includes_reference_block(monkeypatch):
    captured = {}

    def fake_client(payload):
        client = _FakeLLM(payload)
        captured["client"] = client
        return client

    monkeypatch.setattr(
        day_stream, "get_llm_client", lambda: fake_client({"note": "西湖一日", "items": [], "suggestions": []})
    )
    req = GenerateDayRequest(city="杭州", day_no=1, days=1, context=_context())
    day_stream.llm_open_day(req, set())
    system = captured["client"].calls[0]["system"]
    assert "[R1] 西湖风景名胜区" in system
    assert "refs" in system


def test_open_day_without_references_keeps_prompt_clean(monkeypatch):
    captured = {}

    def fake_client(payload):
        client = _FakeLLM(payload)
        captured["client"] = client
        return client

    monkeypatch.setattr(
        day_stream, "get_llm_client", lambda: fake_client({"note": "苏州一日", "items": [], "suggestions": []})
    )
    req = GenerateDayRequest(city="苏州", day_no=1, days=1, context={})
    day_stream.llm_open_day(req, set())
    system = captured["client"].calls[0]["system"]
    assert "[R1]" not in system
    assert "权威参考资料" not in system


# ---------- 单日生成集成 ----------


def test_generate_day_once_grounds_reference_items(monkeypatch):
    """开放模式下命中参考资料的行程项应获得权威字段与真实来源。"""
    amap_calls: list[str] = []

    def fake_ground(item, city, cache):
        amap_calls.append(item.get("poi_name"))

    monkeypatch.setattr(day_stream.settings, "llm_api_key", "test-key")
    monkeypatch.setattr(day_stream, "local_ground", fake_ground)
    monkeypatch.setattr(
        day_stream,
        "get_llm_client",
        lambda: _FakeLLM(
            {
                "note": "杭州一日",
                "items": [
                    {
                        "item_type": "attraction",
                        "poi_name": "西湖",
                        "refs": [1],
                        "start_time": "09:00",
                        "end_time": "11:30",
                        "cost": 999,
                    },
                    {
                        "item_type": "attraction",
                        "poi_name": "自选新景点",
                        "start_time": "13:00",
                        "end_time": "15:00",
                        "cost": 50,
                    },
                ],
                "suggestions": [],
            }
        ),
    )
    plan, source = day_stream.generate_day_once(
        GenerateDayRequest(city="杭州", day_no=1, days=1, context=_context()),
    )

    assert source == "open"
    grounded, external = plan.items
    # refs 引用：名称归一为权威名，字段与来源来自参考资料
    assert grounded.poi_name == "西湖风景名胜区"
    assert grounded.cost == 0
    assert grounded.source == "mysql.poi_knowledge"
    assert grounded.verification_status == "partially_verified"
    assert grounded.fact_evidence["identity"].value_kind == "observed"
    # 未命中项保持开放模式语义，走高德落坐标（替身记录调用）
    assert external.poi_name == "自选新景点"
    assert external.source == "llm.open_day"
    assert external.verification_status == "unverified"
    assert amap_calls == ["自选新景点"]


def test_generate_day_once_external_item_falls_back_to_amap(monkeypatch):
    amap_calls: list[str] = []

    def fake_ground(item, city, cache):
        amap_calls.append(item.get("poi_name"))

    monkeypatch.setattr(day_stream.settings, "llm_api_key", "test-key")
    monkeypatch.setattr(day_stream, "local_ground", fake_ground)
    monkeypatch.setattr(
        day_stream,
        "get_llm_client",
        lambda: _FakeLLM(
            {
                "note": "苏州一日",
                "items": [
                    {"item_type": "attraction", "poi_name": "自选新景点", "start_time": "09:00", "end_time": "11:00"},
                ],
                "suggestions": [],
            }
        ),
    )
    plan, source = day_stream.generate_day_once(
        GenerateDayRequest(city="苏州", day_no=1, days=1, context={}),
        force_fallback=True,
    )
    assert source == "open"
    assert amap_calls == ["自选新景点"]
    assert plan.items[0].source == "llm.open_day"


# ---------- RAGAS 风格评测指标 ----------


def test_reference_metrics_from_pool_stats():
    pool = ReferencePool(_context())
    pool.ground({"item_type": "attraction", "poi_name": "西湖风景名胜区"})
    pool.ground({"item_type": "attraction", "poi_name": "自选", "refs": [2]})
    pool.ground({"item_type": "attraction", "poi_name": "自选2", "refs": [77]})
    metrics = eg.reference_metrics(pool.stats)
    assert metrics["citation_coverage"] == round(2 / 3, 4)
    assert metrics["citation_validity"] == 0.5
    assert metrics["context_utilization"] == 0.5


def test_reference_metrics_empty_case_is_neutral():
    assert eg.reference_metrics({}) == {
        "citation_coverage": 1.0,
        "citation_validity": 1.0,
        "context_utilization": 1.0,
    }


def test_faithfulness_with_injected_judge():
    plans = [{"day_no": 1, "items": [{"poi_name": "西湖风景名胜区", "cost": 0}]}]
    block = ReferencePool(_context()).block()

    def judge(reference_block, plans_json):
        assert "西湖风景名胜区" in reference_block
        assert "西湖风景名胜区" in plans_json
        return [{"text": "西湖免费", "supported": True}, {"text": "雷峰塔票价40", "supported": False}]

    assert eg.faithfulness_score(plans, block, judge) == 0.5


def test_evaluate_generation_skips_faithfulness_without_references():
    metrics = eg.evaluate_generation([], reference_stats={}, reference_block="", judge=None)
    assert "faithfulness" not in metrics
    assert metrics["citation_coverage"] == 1.0


def test_aggregate_ignores_missing_faithfulness():
    aggregate = eg.aggregate_generation_metrics(
        [
            {"citation_coverage": 0.8, "faithfulness": 0.9},
            {"citation_coverage": 1.0},
        ]
    )
    assert aggregate["citation_coverage"] == 0.9
    assert aggregate["faithfulness"] == 0.9
    assert eg.aggregate_generation_metrics([]) == {}


def test_run_generation_case_offline_with_stubs(monkeypatch):
    """注入检索与生成替身，验证评测 case 组装与指标透传。"""
    from app.agent import workflow

    def fake_context(city, preferences):
        return _context()

    def fake_open_plans(req, feedback, hotels, candidates=None, foods=None):
        pool = ReferencePool({"candidates": candidates or [], "foods": foods or [], "hotels": hotels or []})
        plans = [
            {
                "day_no": 1,
                "items": [
                    {"item_type": "attraction", "poi_name": "西湖", "refs": [1]},
                ],
            }
        ]
        for plan in plans:
            for item in plan["items"]:
                pool.ground(item)
        return {"daily_plans": plans, "schedule_report": {"reference_stats": dict(pool.stats)}}

    monkeypatch.setattr(eg, "run_plan_context", fake_context)
    # run_generation_case 在函数内 from app.agent.workflow import generate_open_plans，
    # 因此替身必须打在 workflow 模块上。
    monkeypatch.setattr(workflow, "generate_open_plans", fake_open_plans)

    def judge(reference_block, plans_json):
        return [{"text": "声明", "supported": True}]

    result = eg.run_generation_case("杭州", judge=judge)
    assert result["city"] == "杭州"
    assert result["metrics"] == {
        "citation_coverage": 1.0,
        "citation_validity": 1.0,
        "context_utilization": round(1 / 4, 4),
        "faithfulness": 1.0,
    }
    assert result["reference_stats"]["grounded"] == 1
