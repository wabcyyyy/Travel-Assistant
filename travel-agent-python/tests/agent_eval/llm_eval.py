"""真实 LLM 评测入口。

该脚本不会伪造“真实评测”结果：没有 LLM_API_KEY 时直接退出；运行时记录模型、固定
temperature、知识库城市和两遍结果签名，供分析稳定性、反思重试和 token 成本。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.agent import poi_repository, workflow
from app.agent.day_prompts import GENERATION_TEMPERATURE
from app.agent.observability import observe_run
from app.common.config import settings
from app.prompts.open_generation import OPEN_DAY_PROMPT_VERSION, OPEN_TRIP_PROMPT_VERSION
from app.schemas.trip import GenerateRequest
from tests.agent_eval.metrics import evaluate_narrative, evaluate_response

CASES_PATH = Path(__file__).with_name("cases.json")
THEMED_CASES_PATH = Path(__file__).with_name("themed_cases.json")
REPORT_DIR = Path(__file__).with_name("report")
PROMPT_VERSION = "workflow-v2-authority-route-20260828"

# 生成契约字段白名单：case 里的 name/prompt_version 是评测元数据，
# 不属于 GenerateRequest；intent 等契约字段按白名单自然透传（M5）。
_REQUEST_FIELDS = frozenset(GenerateRequest.model_fields)


def build_generate_request(case: dict) -> GenerateRequest:
    """case → 生成请求：过滤评测元数据（name/prompt_version），intent 透传给生成链路。"""
    return GenerateRequest(**{k: v for k, v in case.items() if k in _REQUEST_FIELDS})


def _catalog(city: str) -> dict:
    return {
        "attractions": poi_repository.search_pois(city, category="attraction", limit=200),
        "foods": poi_repository.search_pois(city, category="food", limit=50),
        "hotels": poi_repository.search_pois(city, category="hotel", limit=30),
        "consumption": poi_repository.get_city_consumption(city) or {},
    }


def _signature(response) -> str:
    return "|".join(
        ">".join(item.poi_name for item in plan.items if item.item_type == "attraction")
        for plan in response.daily_plans
    )


def _trace_stats(trace: dict) -> dict:
    events = trace.get("events") or []
    prompt_tokens = sum(
        int((event.get("metadata") or {}).get("prompt_tokens") or 0)
        for event in events
        if event.get("name") == "llm.request"
    )
    completion_tokens = sum(
        int((event.get("metadata") or {}).get("completion_tokens") or 0)
        for event in events
        if event.get("name") == "llm.request"
    )
    return {
        "llm_calls": sum(event.get("kind") == "llm" and event.get("name") == "llm.request" for event in events),
        "tool_calls": sum(event.get("kind") == "tool" for event in events),
        "retry_count": sum(event.get("kind") == "route" and event.get("name") in ("fix", "retry") for event in events),
        "fallback_count": sum(event.get("kind") == "route" and event.get("name") == "fallback" for event in events),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }


def _run_once(case: dict, suffix: str) -> tuple[dict, str]:
    catalog = _catalog(case["city"])
    response = None
    failure: Exception | None = None
    with observe_run(f"llm-{case['city']}-{case['days']}-{suffix}") as trace:
        try:
            response = workflow.run_generate(build_generate_request(case))
        except Exception as exc:
            failure = exc
    trace_data = trace.to_dict()
    if failure is not None:
        return {
            "run_id": trace_data["run_id"],
            "status": "failed",
            "status_reason": str(failure)[:200],
            "stats": _trace_stats(trace_data),
            "trace": trace_data,
            "quality": None,
            "narrative": None,
        }, ""
    assert response is not None
    quality = evaluate_response(response, case, catalog, trace_data)
    run = {
        "run_id": trace_data["run_id"],
        "status": response.status,
        "status_reason": response.status_reason,
        "stats": _trace_stats(trace_data),
        "trace": trace_data,
        "quality": quality,
        # M5 叙事化指标：与质量指标并列落报告，主题化评测的核心观测面
        "narrative": evaluate_narrative(response, case),
    }
    return run, _signature(response)


def _report_markdown(report: dict) -> str:
    """评测报告的 Markdown 渲染：每 case 一节（固定运行头部 + 指标表）。

    头部固定 model/temperature/两套开放生成 Prompt 版本，指标表合并
    evaluate_response 的质量指标与 evaluate_narrative 的叙事指标；
    无 intent 的基线 case 的主题命中类指标为 None，渲染为 "-"。
    A2 修订：**两种模式都写 .md**（此前 `if themed:` 使非主题化 run 没有 md 产物）。
    """
    themed = report.get("mode") == "real-llm-themed"
    lines = [
        "# 主题化评测报告（真实 LLM）" if themed else "# 真实 LLM 评测报告",
        "",
        f"- model：`{report['model']}` ｜ temperature：{report['temperature']} ｜ "
        f"open_day prompt：`{report['open_day_prompt_version']}` ｜ "
        f"open_trip prompt：`{report['open_trip_prompt_version']}`",
        f"- 用例数：{report['case_count']} ｜ 两遍一致率：{report['consistency_rate']:.2%}",
        "",
    ]
    for detail in report["details"]:
        case = detail["case"]
        run1 = detail["run1"]
        run2 = detail["run2"]
        quality = run1.get("quality") or {}
        narrative = run1.get("narrative") or {}
        title = case.get("name") or f"{case['city']}-{case['days']}d"
        lines += [
            f"## {title}（{case['city']} {case['days']} 日）",
            "",
            f"- prompt_version：`{case.get('prompt_version')}` ｜ "
            f"run1 status：{run1['status']} ｜ run2 status：{run2['status']} ｜ "
            f"两遍一致：{'是' if detail['consistent'] else '否'}",
            "",
            "| 指标 | 结果 |",
            "| --- | ---: |",
        ]
        rows = [
            ("poi_authority_rate", quality.get("poi_authority_rate")),
            ("field_reference_rate", quality.get("field_reference_rate")),
            ("time_conflict_rate", quality.get("time_conflict_rate")),
            ("route_violation_rate", quality.get("route_violation_rate")),
            ("attraction_duplicate_rate", quality.get("attraction_duplicate_rate")),
            ("budget_deviation_rate", quality.get("budget_deviation_rate")),
            ("theme_sentence_rate", narrative.get("theme_sentence_rate")),
            ("why_coverage", narrative.get("why_coverage")),
            ("practical_notes_rate", narrative.get("practical_notes_rate")),
            ("theme_hit_rate", narrative.get("theme_hit_rate")),
            ("poi_relevance", narrative.get("poi_relevance")),
            ("coord_available_rate", narrative.get("coord_available_rate")),
            ("pending_review_count", narrative.get("pending_review_count")),
        ]
        for name, value in rows:
            if value is None:
                shown = "-"
            elif isinstance(value, int) and not isinstance(value, bool):
                shown = str(value)  # 计数型指标（pending_review_count）不按百分比渲染
            else:
                shown = f"{float(value):.2%}"
            lines.append(f"| {name} | {shown} |")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    if not settings.llm_api_key:
        print("未配置 LLM_API_KEY，拒绝冒充真实 LLM 评测；请配置后再运行。", file=sys.stderr)
        return 2
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--cases", default=str(CASES_PATH), help="用例文件：默认 cases.json；主题化同题评测传 themed_cases.json"
    )
    args = parser.parse_args()
    cases_path = Path(args.cases)
    # 文件名以 themed 开头即走主题化报告输出（themed_report.json + .md）
    themed = cases_path.name.startswith("themed")
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    if args.limit:
        cases = cases[: args.limit]
    # prompt_version 占位在运行时填充实际契约版本（M5），随 case 落报告
    cases = [{**case, "prompt_version": f"{OPEN_DAY_PROMPT_VERSION}/{OPEN_TRIP_PROMPT_VERSION}"} for case in cases]
    details = []
    same_count = 0
    status_counts = {"success": 0, "degraded": 0, "failed": 0}
    aggregate_stats = {
        "llm_calls": 0,
        "retry_count": 0,
        "fallback_count": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }
    for case in cases:
        first, signature1 = _run_once(case, "run1")
        second, signature2 = _run_once(case, "run2")
        for run in (first, second):
            status_counts[run["status"]] = status_counts.get(run["status"], 0) + 1
            for key in aggregate_stats:
                aggregate_stats[key] += run["stats"].get(key, 0)
        same = signature1 == signature2
        same_count += same
        details.append(
            {
                "case": case,
                "consistent": same,
                "signature1": signature1,
                "signature2": signature2,
                "run1": first,
                "run2": second,
                "failure_reasons": [
                    run["status_reason"]
                    for run in (first, second)
                    if run.get("status") != "success" and run.get("status_reason")
                ],
            }
        )
    report = {
        # 产物自带新鲜度：口径变更后旧报告可据此识别为过期
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "mode": "real-llm-themed" if themed else "real-llm",
        "model": settings.llm_model,
        # 与开放模式真实生成调用同源（day_prompts.GENERATION_TEMPERATURE）
        "temperature": GENERATION_TEMPERATURE,
        "prompt_version": PROMPT_VERSION,
        # M5：报告头部固定两套开放生成 Prompt 的契约版本
        "open_day_prompt_version": OPEN_DAY_PROMPT_VERSION,
        "open_trip_prompt_version": OPEN_TRIP_PROMPT_VERSION,
        "case_count": len(details),
        "run_count": len(details) * 2,
        "consistency_rate": round(same_count / max(len(details), 1), 4),
        "status_counts": status_counts,
        "aggregate_stats": aggregate_stats,
        "failed_cases": [
            detail["case"]
            for detail in details
            if any(detail[key].get("status") == "failed" for key in ("run1", "run2"))
        ],
        "degraded_cases": [
            detail["case"]
            for detail in details
            if any(detail[key].get("status") == "degraded" for key in ("run1", "run2"))
        ],
        "details": details,
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    # 主题化同题评测（--cases themed_cases.json）输出 themed_report.json+md，
    # 不覆盖既有 llm_report.json
    report_stem = "themed_report" if themed else "llm_report"
    report_path = REPORT_DIR / f"{report_stem}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (REPORT_DIR / f"{report_stem}.md").write_text(_report_markdown(report), encoding="utf-8")
    keys = ("mode", "model", "temperature", "prompt_version", "case_count", "consistency_rate")
    print(json.dumps({k: report[k] for k in keys}, ensure_ascii=False, indent=2))
    print(f"报告已生成：{report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
