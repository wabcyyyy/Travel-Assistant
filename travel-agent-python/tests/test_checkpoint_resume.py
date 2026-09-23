"""断点恢复集成测试（PR-3）：图跑到一半进程死亡 → 重启从 checkpoint 续跑到完成。

PLAN PR-3 验收口径：
1. 图跑到一半模拟进程死亡 → **重启**（全新 compile 的图接同一份检查点存储，进程死亡
   的等价物）从 checkpoint 续跑到完成，且**已完成的超步一个都不重跑**（节点调用
   计数为证——续跑 ≠ 整段重来）；
2. thread_id = 生成任务标识（截断 ≤255）；无检查点时 resume 明确返回 None，不冒充续跑。

"进程死亡"模拟：节点里抛 `KeyboardInterrupt` 子类——它穿过图节点的 `except Exception`
（INV-4 的降级兜底只接 Exception），效果等价进程被杀：没落盘的超步作废，已落盘的还在。
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.agent.generation.orchestration import trip_graph, workflow
from app.agent.runtime import checkpoint
from app.schemas.trip import DailyPlan, GenerateRequest, GenerateResponse


class _ProcessDeath(KeyboardInterrupt):
    """模拟进程死亡（BaseException：穿透节点的 except Exception 兜底）。"""


def test_trip_graph_resumes_from_checkpoint_after_process_death(monkeypatch) -> None:
    calls = {"parse": 0, "research": 0, "generate": 0, "reflect": 0, "format": 0}
    deaths = {"left": 1}

    def parse_requirements(state):
        calls["parse"] += 1
        return {"requirements": {"city": "杭州"}}

    def research_pois(state):
        calls["research"] += 1
        return {"candidates": [{"name": "西湖"}], "foods": [], "hotels": [], "consumption": {}, "research_report": {}}

    def generate_itinerary(state):
        calls["generate"] += 1
        return {"daily_plans": [{"day_no": 1, "items": []}]}

    def reflect(state):
        calls["reflect"] += 1
        if deaths["left"]:
            deaths["left"] -= 1
            raise _ProcessDeath()
        return {"validation_issues": [], "validation_log": []}

    def format_output(state):
        calls["format"] += 1
        return {"result": GenerateResponse(city="杭州", days=1, title="t", daily_plans=[], budget_estimate={})}

    monkeypatch.setattr(workflow, "parse_requirements", parse_requirements)
    monkeypatch.setattr(workflow, "research_pois", research_pois)
    monkeypatch.setattr(workflow, "generate_itinerary", generate_itinerary)
    monkeypatch.setattr(workflow, "reflect", reflect)
    monkeypatch.setattr(workflow, "needs_fix", lambda state: "pass")
    monkeypatch.setattr(workflow, "format_output", format_output)

    thread = f"test-resume-{uuid4().hex}"
    with pytest.raises(_ProcessDeath):
        trip_graph.run_trip(GenerateRequest(city="杭州", days=1), thread_id=thread)
    assert calls == {"parse": 1, "research": 1, "generate": 1, "reflect": 1, "format": 0}, (
        "死在 reflect：parse/research/generate 三个超步已落检查点"
    )

    # 重启 = 全新 compile 的图对象接同一份检查点存储（进程死亡的等价物）
    revived = trip_graph.build_unified_graph().compile(checkpointer=checkpoint.get_checkpointer())
    result = revived.invoke(None, checkpoint.run_config(thread))
    assert calls == {"parse": 1, "research": 1, "generate": 1, "reflect": 2, "format": 1}, (
        "续跑只补没落盘的部分：已完成超步一个都不重跑（整段重跑 = 计数翻倍）"
    )
    assert result["result"].city == "杭州", "续跑到完成，产出照常交付"


def test_resume_returns_none_without_checkpoint_and_thread_id_is_truncated() -> None:
    """无检查点不冒充续跑；thread_id 按 checkpoints 列宽截断 ≤255（官方列宽坑）。"""
    assert trip_graph.resume_run(f"missing-{uuid4().hex}") is None
    assert trip_graph.resume_day(f"missing-{uuid4().hex}") is None
    long_thread = checkpoint.checkpoint_thread_id("x" * 400)
    assert len(long_thread) == checkpoint.THREAD_ID_MAX == 255
    assert checkpoint.run_config("day-1-2") == {"configurable": {"thread_id": "day-1-2"}}


def test_thread_reuse_starts_fresh_run(monkeypatch) -> None:
    """同一 thread 再跑 = 新 run（day 状态全量重置）：重复恢复/重试不与旧历史串味。"""
    plans = [
        DailyPlan(day_no=1, note="第一轮"),
        DailyPlan(day_no=1, note="第二轮"),
    ]
    attempts = {"n": 0}

    def fake_once(req, *, force_fallback=False):
        plan = plans[attempts["n"]]
        attempts["n"] += 1
        return plan, "llm"

    from app.agent.generation.orchestration import day_workflow

    monkeypatch.setattr(day_workflow, "generate_day_once", fake_once)
    thread = f"test-reuse-{uuid4().hex}"
    request_kwargs = {"city": "杭州", "day_no": 1, "action_id": thread}
    first = trip_graph.run_day(trip_graph.GenerateDayRequest(**request_kwargs), thread_id=thread)
    second = trip_graph.run_day(trip_graph.GenerateDayRequest(**request_kwargs), thread_id=thread)
    assert first.note == "第一轮" and second.note == "第二轮", "重放同一 thread 不吃旧状态（attempts/plan 全量重置）"
    assert attempts["n"] == 2


def test_cleanup_old_threads_removes_expired_history(monkeypatch) -> None:
    """保留期清理（LangGraph 官方告警：checkpoints 无限增长）：过期 thread 整条删除。"""
    from app.agent.generation.orchestration import day_workflow

    monkeypatch.setattr(
        day_workflow,
        "generate_day_once",
        lambda req, *, force_fallback=False: (
            DailyPlan(day_no=1, note="待清理"),
            "llm",
        ),
    )
    thread = f"test-cleanup-{uuid4().hex}"
    trip_graph.run_day(trip_graph.GenerateDayRequest(city="杭州", day_no=1, action_id=thread), thread_id=thread)
    assert trip_graph.resume_day(thread) is not None, "先确认这条 thread 有检查点"
    assert checkpoint.cleanup_old_threads(0) >= 1, "retention=0：全部过期"
    assert trip_graph.resume_day(thread) is None, "过期 thread 整条删掉，续跑入口回到 None"
