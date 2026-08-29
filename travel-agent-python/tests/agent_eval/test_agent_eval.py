from tests.agent_eval.eval_agent import build_report
from tests.agent_eval import mock_llm


def test_offline_agent_evaluation_covers_workflow_and_authority():
    report = build_report([{"city": "杭州", "days": 2, "persons": 2, "preferences": ["自然风光"]}])
    metrics = report["metrics"]
    assert metrics["poi_authority_rate"] == 1.0
    assert metrics["field_reference_rate"] == 1.0
    assert metrics["time_conflict_rate"] == 0.0
    assert metrics["route_violation_rate"] == 0.0
    assert metrics["attraction_duplicate_rate"] == 0.0
    assert metrics["budget_deviation_rate"] == 0.0
    assert metrics["success_status_rate"] == 0.0
    assert metrics["degraded_status_rate"] == 1.0
    assert metrics["failed_status_rate"] == 0.0
    assert metrics["fallback_success_rate"] == 1.0
    assert metrics["trace_complete_rate"] == 1.0
