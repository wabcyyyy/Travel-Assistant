import httpx
import pytest

from eval_agent import AGENT_URL, build_cases, evaluate_one


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=AGENT_URL, timeout=60.0) as c:
        yield c


@pytest.mark.parametrize("idx", [0, 1, 2])
def test_eval_smoke(client, idx):
    cases = build_cases(6)
    result = evaluate_one(client, cases[idx])
    assert result["toolAccuracy"] == 1.0
    assert result["conflictRate"] == 0.0
    assert result["dupRate"] == 0.0
    assert result["hallucinationRate"] == 0.0
    assert result["budgetDeviation"] == 0.0
    assert len(result["hallucinations"]) == 0