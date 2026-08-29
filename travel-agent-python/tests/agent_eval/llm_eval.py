"""真实 LLM 评测入口。

该脚本不会伪造“真实评测”结果：没有 LLM_API_KEY 时直接退出；运行时记录模型、固定
temperature、知识库城市和两遍结果签名，供分析稳定性、反思重试和 token 成本。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.agent import poi_repository, workflow
from app.agent.observability import observe_run
from app.common.config import settings
from app.schemas.trip import GenerateRequest
from tests.agent_eval.metrics import evaluate_response

CASES_PATH = Path(__file__).with_name("cases.json")
REPORT_DIR = Path(__file__).with_name("report")
PROMPT_VERSION = "workflow-v2-authority-route-20260828"


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
        for event in events if event.get("name") == "llm.request"
    )
    completion_tokens = sum(
        int((event.get("metadata") or {}).get("completion_tokens") or 0)
        for event in events if event.get("name") == "llm.request"
    )
    return {
        "llm_calls": sum(
            event.get("kind") == "llm" and event.get("name") == "llm.request"
            for event in events
        ),
        "tool_calls": sum(event.get("kind") == "tool" for event in events),
        "retry_count": sum(
            event.get("kind") == "route" and event.get("name") in ("fix", "retry")
            for event in events
        ),
        "fallback_count": sum(
            event.get("kind") == "route" and event.get("name") == "fallback"
            for event in events
        ),
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
            response = workflow.run_generate(GenerateRequest(**case))
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
    }
    return run, _signature(response)


def main() -> int:
    if not settings.llm_api_key:
        print("未配置 LLM_API_KEY，拒绝冒充真实 LLM 评测；请配置后再运行。", file=sys.stderr)
        return 2
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    if args.limit:
        cases = cases[:args.limit]
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
        details.append({
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
        })
    report = {
        "mode": "real-llm",
        "model": settings.llm_model,
        "temperature": 0.3,
        "prompt_version": PROMPT_VERSION,
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
    (REPORT_DIR / "llm_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("mode", "model", "temperature", "prompt_version", "case_count", "consistency_rate")}, ensure_ascii=False, indent=2))
    print(f"报告已生成：{REPORT_DIR / 'llm_report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
