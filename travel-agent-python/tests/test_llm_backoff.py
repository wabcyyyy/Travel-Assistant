"""LLM 重试退避抖动单测（L1 补充 3：注释是意图，代码向注释对齐）。

抖动带回无法逐值断言，验收口径 = 区间钳制 + 随机分量存在：
- 区间：min(2^attempt × 0.3, 2.0) × [0.8, 1.2]；
- 随机分量：同 attempt 大样本采样必有多值（无抖动时恒等于基数）。
"""

from __future__ import annotations

import random

import pytest

import app.agent  # noqa: F401  先完成 agent 门面导入：存量导入环 llm_client→facade→web_search→llm_client（pyproject importlinter 豁免条目注明的既有债）。
from app.common import llm_client


def _base(attempt: int) -> float:
    return min(2.0**attempt * 0.3, 2.0)


def test_backoff_delay_stays_within_jitter_band():
    for attempt in range(5):
        base = _base(attempt)
        values = [llm_client._backoff_delay(attempt) for _ in range(200)]
        assert all(base * 0.8 <= v <= base * 1.2 for v in values), f"attempt={attempt} 的退避必须落在 ±20% 抖动带内"


def test_backoff_has_random_component():
    values = {round(llm_client._backoff_delay(2), 6) for _ in range(50)}
    assert len(values) > 1, "退避序列必须有随机分量（同步网关的瞬时过载会被整齐的重试波放大）"


def test_backoff_fixed_seed_is_reproducible():
    """固定种子断言区间与取值（L1 验收字面口径）：种子 → uniform 抽样可复现。"""
    random.seed(42)
    first = llm_client._backoff_delay(2)
    random.seed(42)
    second = llm_client._backoff_delay(2)
    assert first == second, "同一固定种子下退避序列必须可复现"
    expected = min(2.0**2 * 0.3, 2.0) * random.Random(42).uniform(0.8, 1.2)
    assert first == pytest.approx(expected)


def test_retry_sleep_sleeps_jittered_delay(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr(llm_client.time, "sleep", sleeps.append)
    llm_client._retry_sleep(1)
    assert len(sleeps) == 1
    base = _base(1)
    assert base * 0.8 <= sleeps[0] <= base * 1.2
