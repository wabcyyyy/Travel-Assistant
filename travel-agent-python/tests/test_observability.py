from app.agent.observability import metrics, observe_run
from app.agent.trace import record_event


def test_observe_run_aggregates_llm_tools_retries_and_tokens():
    metrics.reset()
    with observe_run("test-run"):
        record_event("llm", "llm.generate")
        record_event("llm", "llm.request", metadata={"prompt_tokens": 100, "completion_tokens": 20})
        record_event("tool", "poi.search_attractions")
        record_event("route", "retry")
        record_event("route", "fallback")
        record_event("decision", "run_status", metadata={"status": "degraded"})
    snapshot = metrics.snapshot()
    assert snapshot["runs"] == 1
    assert snapshot["successes"] == 0
    assert snapshot["degraded_runs"] == 1
    assert snapshot["degraded_rate"] == 1.0
    assert snapshot["llm_calls"] == 1
    assert snapshot["tool_calls"] == 1
    assert snapshot["validation_retries"] == 1
    assert snapshot["fallback_runs"] == 1
    assert snapshot["prompt_tokens"] == 100
    assert snapshot["completion_tokens"] == 20


def test_observe_run_aggregates_mcp_failures():
    metrics.reset()
    with observe_run("mcp-run"):
        record_event("mcp", "amap.search_poi", status="error", error="timeout")
    snapshot = metrics.snapshot()
    assert snapshot["mcp_calls"] == 1
    assert snapshot["mcp_failures"] == 1
    assert snapshot["mcp_failure_rate"] == 1.0


def test_observe_run_keeps_error_as_failed_run():
    metrics.reset()
    try:
        with observe_run("failed-run"):
            record_event("tool", "amap.search_poi", status="error", error="timeout")
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    snapshot = metrics.snapshot()
    assert snapshot["failures"] == 1
    assert snapshot["recent_failures"][0]["run_id"] == "failed-run"
    failed_trace = metrics.get_trace("failed-run")
    assert failed_trace is not None
    assert any(
        event["name"] == "run_status"
        and event["metadata"]["status"] == "failed"
        for event in failed_trace["events"]
    )


def test_observe_run_allows_recent_trace_lookup_and_expires_old_entries():
    metrics.reset()
    with observe_run("lookup-run"):
        record_event("node", "parse")
    trace = metrics.get_trace("lookup-run")
    assert trace is not None
    assert trace["run_id"] == "lookup-run"
    assert trace["events"][0]["name"] == "parse"

    for index in range(101):
        with observe_run(f"run-{index}"):
            record_event("node", "parse")
    assert metrics.get_trace("lookup-run") is None
    assert metrics.get_trace("run-0") is None
    assert metrics.get_trace("run-100") is not None
