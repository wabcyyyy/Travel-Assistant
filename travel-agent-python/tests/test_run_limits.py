import pytest

from app.agent.run_limits import RunLimitExceeded, RunLimits


def test_run_limits_enforce_llm_and_token_budgets():
    limits = RunLimits(deadline_seconds=60, max_llm_calls=1, max_tokens=10)
    limits.check("llm")
    limits.record_llm(5, 5)
    with pytest.raises(RunLimitExceeded, match="模型调用"):
        limits.check("llm")

    limits = RunLimits(deadline_seconds=60, max_llm_calls=2, max_tokens=10)
    with pytest.raises(RunLimitExceeded, match="Token"):
        limits.record_llm(8, 3)


def test_run_limits_detect_no_progress():
    limits = RunLimits(deadline_seconds=60, max_llm_calls=2, max_tokens=10, max_replans=3)
    limits.record_replan(False)
    with pytest.raises(RunLimitExceeded, match="无进展"):
        limits.record_replan(False)
