"""评测防倒退门禁的单测（SPEC v2.3 §8 A2 / §12）。

`check()` 是纯函数：这里逐类钉住通过线与四类红灯（failed / 版本漂移 / 一致率倒退 /
字段缺失），并显式钉住「degraded 不判失败」这条纪律——它是防口径造假的护栏。
`main()` 只测 guard 分支（无 key 跳过 / 报告缺失），不触网。
"""

from __future__ import annotations

from tests.agent_eval import eval_gate


def _report(**overrides) -> dict:
    base = {
        "mode": "real-llm",
        "prompt_version": eval_gate.EXPECTED_PROMPT_VERSION,
        "open_day_prompt_version": eval_gate.EXPECTED_OPEN_DAY_PROMPT_VERSION,
        "open_trip_prompt_version": eval_gate.EXPECTED_OPEN_TRIP_PROMPT_VERSION,
        "case_count": 3,
        "run_count": 6,
        "status_counts": {"success": 0, "degraded": 6, "failed": 0},
        "consistency_rate": 0.1667,
    }
    base.update(overrides)
    return base


def test_gate_passes_on_baseline_report() -> None:
    assert eval_gate.check(_report()) == []


def test_degraded_is_never_treated_as_failure() -> None:
    """degraded 是本项目如实呈现的状态；判失败会逼出口径造假（A2 纪律）。"""
    report = _report(status_counts={"success": 0, "degraded": 12, "failed": 0})
    assert eval_gate.check(report) == []


def test_failed_run_is_hard_failure() -> None:
    problems = eval_gate.check(
        _report(status_counts={"success": 10, "degraded": 1, "failed": 1})
    )
    assert any("failed" in problem for problem in problems)


def test_prompt_version_drift_is_flagged() -> None:
    problems = eval_gate.check(_report(open_day_prompt_version="v9.9.next"))
    assert any("open_day_prompt_version" in problem for problem in problems)

    problems = eval_gate.check(_report(prompt_version="workflow-v3"))
    assert any("prompt_version" in problem for problem in problems)


def test_consistency_regression_is_flagged() -> None:
    problems = eval_gate.check(_report(consistency_rate=0.0))
    assert any("一致率" in problem for problem in problems)


def test_missing_consistency_rate_is_flagged() -> None:
    report = _report()
    report.pop("consistency_rate")
    assert eval_gate.check(report)


def test_main_skips_without_llm_key(monkeypatch, capsys) -> None:
    monkeypatch.setattr(eval_gate.settings, "llm_api_key", "")
    assert eval_gate.main(["eval_gate"]) == 0
    assert "跳过" in capsys.readouterr().out


def test_main_fails_when_report_missing(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(eval_gate.settings, "llm_api_key", "example-key")
    assert eval_gate.main(["eval_gate", str(tmp_path / "nope.json")]) == 1


def test_main_reads_report_and_reports_problems(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setattr(eval_gate.settings, "llm_api_key", "example-key")
    path = tmp_path / "llm_report.json"
    path.write_text('{"mode": "real-llm"}', encoding="utf-8")
    assert eval_gate.main(["eval_gate", str(path)]) == 1
    assert "未通过" in capsys.readouterr().out
