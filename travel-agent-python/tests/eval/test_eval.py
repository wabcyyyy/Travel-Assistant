import httpx
import pytest

from eval_agent import AGENT_URL, LLM_MODE, build_cases, evaluate_one


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=AGENT_URL, timeout=120.0) as c:
        yield c


def assert_within(actual, expected, tolerance=0.01):
    assert abs(actual - expected) <= tolerance


@pytest.mark.parametrize("idx", [0, 1, 2])
def test_eval_smoke(client, idx):
    cases = build_cases(6)
    result = evaluate_one(client, cases[idx])
    assert result["days"] >= 1
    assert result["totalItems"] >= 3
    if LLM_MODE:
        assert_within(result["toolAccuracy"], 1.0, 0.2)
        assert_within(result["conflictRate"], 0.0, 0.5)
        assert_within(result["dupRate"], 0.0, 0.3)
        assert_within(result["hallucinationRate"], 0.0, 0.3)
    else:
        assert result["totalItems"] >= 5
        assert_within(result["toolAccuracy"], 1.0)
        assert_within(result["conflictRate"], 0.0)
        assert_within(result["dupRate"], 0.0)
        assert_within(result["hallucinationRate"], 0.0)
        assert_within(result["budgetDeviation"], 0.0)