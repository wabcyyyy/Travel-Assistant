"""多 Agent 研究层测试：证据包契约 / Supervisor 整合 / 单域容错 / LLM 推理循环 / 缺口补查 / workflow 接入。"""

from unittest.mock import patch

import pytest

from app.agent import tools, workflow
from app.agent.research import reasoning
from app.agent.research import (
    ResearchTask,
    decompose,
    run_refill,
    run_research,
    run_research_context,
)
from app.agent.research.reasoning import (
    evaluate_research as _real_evaluate,
)
from app.schemas.trip import GenerateRequest
from tests.agent_eval import mock_llm


@pytest.fixture(autouse=True)
def _mock_research_reasoning(monkeypatch):
    """默认把研究 Agent 的 LLM 推理替换为确定性 fixture（等价阶段一行为）。"""
    monkeypatch.setattr(reasoning, "plan_research", mock_llm.plan_research)
    monkeypatch.setattr(reasoning, "evaluate_research", mock_llm.evaluate_research)


@pytest.fixture(autouse=True)
def _disable_web_refill(monkeypatch):
    """研究 Agent 单测关闭联网补池：.env 带 LLM_API_KEY 时 _run_search 的
    web 分支会真实出网（成功/401 均有可能），导致证据条数断言环境性抖动。
    基线行为即"联网不可用"，这里显式固定，保证单测封闭可复现。"""
    monkeypatch.setattr("app.agent.web_search.settings.web_search_enabled", False)


def _patch_catalog():
    """与其它 workflow 测试一致的工具注入：研究 Agent 运行时经 tools 模块解析。"""
    return (
        patch.object(tools, "search_attractions", mock_llm.search_attractions),
        patch.object(tools, "search_foods", mock_llm.search_foods),
        patch.object(tools, "search_hotels", mock_llm.search_hotels),
        patch.object(tools, "get_consumption", mock_llm.get_consumption),
    )


def test_run_research_produces_evidence_pack_for_each_domain():
    """每个研究域都产出符合契约的证据包（items/confidence/rounds/gaps/degraded）。"""
    patches = _patch_catalog()
    for item in patches:
        item.start()
    try:
        for domain, expected in (("attraction", 12), ("food", 4), ("hotel", 2)):
            pack = run_research(ResearchTask(domain=domain, city="杭州", limit=30))
            assert pack.domain == domain
            assert len(pack.items) == expected
            # 离线 fixture 无来源标注 → 整包视为证据可信
            assert pack.confidence == 1.0
            assert pack.rounds == 1
            assert pack.gaps == []
            assert pack.degraded is False
            summary = pack.to_dict()
            assert summary["count"] == expected
    finally:
        for item in reversed(patches):
            item.stop()


def test_empty_research_marks_gap_and_degraded(monkeypatch):
    """检索结果为空时：缺口提示 + degraded 标记，不伪造证据。"""
    monkeypatch.setattr(tools, "search_attractions", lambda *_a, **_k: [])
    pack = run_research(ResearchTask(domain="attraction", city="未知地", limit=30))
    assert pack.items == []
    assert pack.degraded is True
    assert pack.gaps and "未检索到景点" in pack.gaps[0]


def test_supervisor_synthesizes_context_shape(monkeypatch):
    """Supervisor 整合后返回旧上下文契约（candidates/foods/hotels/consumption）。"""
    monkeypatch.setattr(tools, "search_attractions", mock_llm.search_attractions)
    monkeypatch.setattr(tools, "search_foods", mock_llm.search_foods)
    monkeypatch.setattr(tools, "search_hotels", mock_llm.search_hotels)
    monkeypatch.setattr(tools, "get_consumption", mock_llm.get_consumption)
    context = run_research_context(GenerateRequest(city="杭州", days=1))
    assert len(context["candidates"]) == 12
    assert len(context["foods"]) == 4
    assert len(context["hotels"]) == 2
    assert context["consumption"]["meal_price"] == 60
    research = context["research_report"]
    assert research["mode"] == "supervisor"
    assert set(research["agents"]) == {"attraction", "food", "hotel"}
    assert research["agents"]["hotel"]["count"] == 2


def test_supervisor_tolerates_single_domain_failure(monkeypatch):
    """单个研究域异常 → 该域降级为 degraded 证据包，不阻塞其余域与整合。"""
    monkeypatch.setattr(tools, "search_attractions", mock_llm.search_attractions)
    monkeypatch.setattr(tools, "search_foods", mock_llm.search_foods)
    monkeypatch.setattr(tools, "get_consumption", mock_llm.get_consumption)

    def boom(*_args, **_kwargs):
        raise RuntimeError("amap down")

    monkeypatch.setattr(tools, "search_hotels", boom)
    context = run_research_context(GenerateRequest(city="杭州", days=1))
    # 景点/美食不受影响，酒店降级为空证据包
    assert len(context["candidates"]) == 12
    assert len(context["foods"]) == 4
    assert context["hotels"] == []
    hotel = context["research_report"]["agents"]["hotel"]
    assert hotel["degraded"] is True
    assert hotel["count"] == 0
    assert any("研究失败" in gap for gap in hotel["gaps"])


def test_decompose_builds_three_tasks():
    req = GenerateRequest(city="丽江", days=3, preferences=["自然风光"], hotel_tier="奢华型")
    tasks = decompose(req)
    assert [t.domain for t in tasks] == ["attraction", "food", "hotel"]
    attraction = tasks[0]
    assert attraction.city == "丽江"
    assert attraction.preferences == ["自然风光"]
    assert tasks[2].hotel_tier == "奢华型"


def test_workflow_search_node_writes_research_report(monkeypatch):
    """workflow 整段生成：search 节点走 Supervisor 研究，research_report 随 schedule_report 透出。"""
    monkeypatch.setattr(workflow.settings, "llm_api_key", "configured")
    monkeypatch.setattr(workflow.settings, "live_price_search", False)
    monkeypatch.setattr(tools, "search_attractions", mock_llm.search_attractions)
    monkeypatch.setattr(tools, "search_foods", mock_llm.search_foods)
    monkeypatch.setattr(tools, "search_hotels", mock_llm.search_hotels)
    monkeypatch.setattr(tools, "get_consumption", mock_llm.get_consumption)
    monkeypatch.setattr(workflow, "_amap_ground", lambda *_a, **_k: None)
    monkeypatch.setattr(workflow, "_llm_open_day", mock_llm.fixture_open_day)

    response = workflow.run_generate(GenerateRequest(city="杭州", days=1))
    research = (response.schedule_report or {}).get("research") or {}
    assert set(research.get("agents") or {}) == {"attraction", "food", "hotel"}
    assert research["mode"] == "supervisor"
    # 开放模式结果正常交付（fixture 引用命中候选 → partially_verified）
    assert response.quality_report.quality_status == "READY_WITH_WARNINGS"
    assert any(item.source != "llm.open_day" for day in response.daily_plans for item in day.items)


# ---------- 阶段二：研究 Agent LLM 推理循环 ----------


def test_research_planner_expands_attraction_preferences(monkeypatch):
    """规划输出扩展偏好与规模 → 检索节点按其执行。"""
    captured = {}

    def fake_search(city, preferences, limit=30):
        captured["preferences"] = list(preferences)
        captured["limit"] = limit
        return [{"name": f"{city}景1", "latitude": 30.0, "longitude": 120.0}]

    monkeypatch.setattr(tools, "search_attractions", fake_search)
    monkeypatch.setattr(reasoning, "plan_research", lambda task: {
        "preferences": ["亲子"], "extra_keywords": [], "limit": 40})

    pack = run_research(ResearchTask(domain="attraction", city="杭州",
                                     preferences=["自然风光"], limit=30))
    assert captured["preferences"] == ["自然风光", "亲子"]
    assert captured["limit"] == 40
    assert len(pack.items) == 1
    assert pack.rounds == 1


def test_research_evaluate_insufficient_triggers_refine_round(monkeypatch):
    """评估不足 → 补查一轮：补充关键词经高德并入证据，轮次=2。"""
    calls = {"n": 0}

    def fake_search(city, preferences, limit=30):
        calls["n"] += 1
        return [{"name": f"{city}景点{calls['n']}", "latitude": 30.0, "longitude": 120.0}]

    def fake_amap(city, keyword, *, category=None):
        return [{"name": f"{city}补充点", "latitude": 30.1, "longitude": 120.1}]

    monkeypatch.setattr(tools, "search_attractions", fake_search)
    monkeypatch.setattr(tools, "search_amap_poi", fake_amap)
    monkeypatch.setattr(reasoning, "plan_research", lambda task: {})
    monkeypatch.setattr(reasoning, "evaluate_research", lambda task, items, round_no:
                        {"sufficient": False, "extra_keywords": ["杭州 西湖"]})

    pack = run_research(ResearchTask(domain="attraction", city="杭州"))
    assert pack.rounds == 2
    names = {p["name"] for p in pack.items}
    assert "杭州补充点" in names  # 补充关键词的检索结果已并入证据


def test_reasoning_evaluate_empty_is_deterministic_insufficient(monkeypatch):
    """证据为空时评估确定性判定不足并给默认补充词，不触发模型调用。"""
    monkeypatch.setattr(reasoning.settings, "llm_api_key", "configured")
    verdict = _real_evaluate(ResearchTask(domain="food", city="杭州"), [], 1)
    assert verdict["sufficient"] is False
    assert any("美食" in kw for kw in verdict["extra_keywords"])


# ---------- 阶段二：Supervisor 缺口补查 ----------


def test_supervisor_refill_merges_evidence_and_regenerates(monkeypatch):
    """校验发现"未安排任何景点" → Supervisor 补查景点研究 Agent → 再生成后补齐景点。"""
    monkeypatch.setattr(workflow.settings, "llm_api_key", "configured")
    monkeypatch.setattr(workflow.settings, "live_price_search", False)
    monkeypatch.setattr(tools, "search_foods", mock_llm.search_foods)
    monkeypatch.setattr(tools, "search_hotels", mock_llm.search_hotels)
    monkeypatch.setattr(tools, "get_consumption", mock_llm.get_consumption)
    monkeypatch.setattr(workflow, "_amap_ground", lambda *_a, **_k: None)

    state = {"calls": 0}

    def search_attractions(city, preferences, limit=30):
        state["calls"] += 1
        if state["calls"] == 1:
            return []  # 首轮无景点证据 → 生成只有酒店 → 触发补查
        return [{"id": 1, "name": "补查景点", "category": "attraction",
                 "latitude": 30.0, "longitude": 120.0, "ticket_price": 40,
                 "duration_min": 120, "open_time": "08:00-18:00"}]

    monkeypatch.setattr(tools, "search_attractions", search_attractions)

    def open_day(req, _used):
        candidates = (req.context or {}).get("candidates") or []
        if not candidates:
            # 首轮仅酒店 → 校验「未安排任何景点」→ 触发补查
            return {"note": "杭州行程", "items": [
                {"item_type": "hotel", "poi_name": "杭州舒适酒店", "cost": 350,
                 "start_time": "18:00", "end_time": "18:30", "duration_min": 30,
                 "latitude": 30.05, "longitude": 120.05},
            ]}
        name = candidates[0]["name"]
        # 补查后：含景点+餐饮且时长达标，避免 quality BLOCKED
        return {"note": "杭州行程", "items": [
            {"item_type": "attraction", "poi_name": name,
             "start_time": "09:00", "end_time": "12:00", "duration_min": 180,
             "latitude": 30.0, "longitude": 120.0, "cost": 0},
            {"item_type": "food", "poi_name": "杭州餐厅",
             "start_time": "12:40", "end_time": "13:40", "duration_min": 60,
             "latitude": 30.01, "longitude": 120.01, "cost": 70},
            {"item_type": "attraction", "poi_name": "杭州公园",
             "start_time": "14:10", "end_time": "16:10", "duration_min": 120,
             "latitude": 30.02, "longitude": 120.02, "cost": 0},
            {"item_type": "hotel", "poi_name": "杭州舒适酒店", "cost": 350,
             "start_time": "18:00", "end_time": "18:30", "duration_min": 30,
             "latitude": 30.05, "longitude": 120.05},
        ]}

    monkeypatch.setattr(workflow, "_llm_open_day", open_day)

    response = workflow.run_generate(GenerateRequest(city="杭州", days=1))
    names = [item.poi_name for day in response.daily_plans for item in day.items]
    assert "补查景点" in names
    research = (response.schedule_report or {}).get("research") or {}
    assert research["agents"]["attraction"].get("refilled") is True
    assert research["agents"]["attraction"]["count"] == 1
    assert response.quality_report.quality_status == "READY_WITH_WARNINGS"


def test_refill_not_triggered_for_non_evidence_gap(monkeypatch):
    """路线/时间类校验问题不是证据型缺口 → 走正常 fix，不派发补查。"""
    monkeypatch.setattr(workflow.settings, "llm_api_key", "configured")
    monkeypatch.setattr(workflow.settings, "live_price_search", False)
    monkeypatch.setattr(tools, "search_attractions", mock_llm.search_attractions)
    monkeypatch.setattr(tools, "search_foods", mock_llm.search_foods)
    monkeypatch.setattr(tools, "search_hotels", mock_llm.search_hotels)
    monkeypatch.setattr(tools, "get_consumption", mock_llm.get_consumption)
    monkeypatch.setattr(workflow, "_amap_ground", lambda *_a, **_k: None)

    def open_day(req, _used):
        # 两个景点时间重叠 → 时间冲突（非证据缺口）
        return {"note": "杭州行程", "items": [
            {"item_type": "attraction", "poi_name": "杭州景点1",
             "start_time": "09:00", "end_time": "11:00", "duration_min": 120,
             "latitude": 30.0, "longitude": 120.0, "cost": 20},
            {"item_type": "attraction", "poi_name": "杭州景点2",
             "start_time": "10:00", "end_time": "12:00", "duration_min": 120,
             "latitude": 30.1, "longitude": 120.1, "cost": 30},
        ]}

    monkeypatch.setattr(workflow, "_llm_open_day", open_day)

    response = workflow.run_generate(GenerateRequest(city="杭州", days=1))
    research = (response.schedule_report or {}).get("research") or {}
    # 校验耗尽后保留结果并降级，但景点证据未发生补查
    assert research["agents"]["attraction"].get("refilled") is not True
    assert "保留" in (response.status_reason or "")
    assert response.quality_report.quality_status == "BLOCKED"


def test_run_refill_task_is_more_aggressive(monkeypatch):
    """run_refill 使用更大的检索规模与扩展偏好。"""
    captured = {}

    def fake_search(city, preferences, limit=30):
        captured["preferences"] = list(preferences)
        captured["limit"] = limit
        return [{"name": "补查点", "latitude": 30.0, "longitude": 120.0}]

    monkeypatch.setattr(tools, "search_attractions", fake_search)
    req = GenerateRequest(city="杭州", days=1, preferences=["自然风光"])
    pack = run_refill("attraction", req)
    assert captured["limit"] == 60
    assert "热门" in captured["preferences"]
    assert len(pack.items) == 1
