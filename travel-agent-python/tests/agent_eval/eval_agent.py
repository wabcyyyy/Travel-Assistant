"""离线 Agent 评测入口。

用法：
    uv run python tests/agent_eval/eval_agent.py

评测使用固定权威 fixture 数据 + mock 开放模式输出（fixture_open_day/trip），
不依赖 MySQL、外部 API 或真实 LLM，走真实的编排/引用落地/反思/格式化链路；
报告可以在面试前稳定复现。真实 LLM 评测应在此基础上固定模型/temperature/Prompt 版本另跑。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.agent import tools, workflow
from app.agent.research import reasoning
from app.agent.route_service import clear_route_cache
from app.agent.trace import trace_run
from app.prompts.open_generation import OPEN_DAY_PROMPT_VERSION, OPEN_TRIP_PROMPT_VERSION
from app.schemas.trip import GenerateRequest
from tests.agent_eval import mock_llm
from tests.agent_eval.metrics import evaluate_response

CASES_PATH = Path(__file__).with_name("cases.json")
REPORT_DIR = Path(__file__).with_name("report")

# 生成契约字段白名单：case 里的 name/prompt_version 是评测元数据，
# 不属于 GenerateRequest；intent 等契约字段按白名单自然透传（M5）。
_REQUEST_FIELDS = frozenset(GenerateRequest.model_fields)


def build_generate_request(case: dict) -> GenerateRequest:
    """case → 生成请求：过滤评测元数据（name/prompt_version），intent 透传给生成链路。"""
    return GenerateRequest(**{k: v for k, v in case.items() if k in _REQUEST_FIELDS})


def with_prompt_version(case: dict) -> dict:
    """运行时填充 prompt_version 占位：报告里的 case 记录实际生成契约版本。"""
    return {**case, "prompt_version": f"{OPEN_DAY_PROMPT_VERSION}/{OPEN_TRIP_PROMPT_VERSION}"}


def run_case(case: dict) -> dict:
    case = with_prompt_version(case)
    # 路线缓存属于进程级优化；每个 fixture 用例先清空，避免前一个城市的
    # 缓存改变本用例的 Trace 工具数和耗时，保证报告可复现。
    clear_route_cache()
    fixture = mock_llm.catalog(case["city"])
    # LLM-only 口径下的离线评测：mock 开放模式的模型输出（而非旧的
    # 确定性 fallback），走真实的编排/引用落地/反思/格式化链路。
    with (
        patch.object(workflow.settings, "llm_api_key", "fixture"),
        patch.object(tools, "search_attractions", mock_llm.search_attractions),
        patch.object(tools, "search_foods", mock_llm.search_foods),
        patch.object(tools, "get_consumption", mock_llm.get_consumption),
        patch.object(tools, "search_hotels", mock_llm.search_hotels),
        patch.object(reasoning, "plan_research", mock_llm.plan_research),
        patch.object(reasoning, "evaluate_research", mock_llm.evaluate_research),
        patch.object(tools, "attach_poi_images", mock_llm.attach_poi_images),
        patch.object(tools, "search_local_poi", mock_llm.search_local_poi),
        patch.object(workflow, "llm_open_day", mock_llm.fixture_open_day),
        patch.object(workflow, "llm_open_trip", mock_llm.fixture_open_trip),
        trace_run(f"fixture-{case['city']}-{case['days']}") as recorder,
    ):
        response = workflow.run_generate(build_generate_request(case))
    return evaluate_response(response, case, fixture, recorder.to_dict())


def _average(results: list[dict], key: str) -> float:
    return round(sum(result[key] for result in results) / max(len(results), 1), 4)


def build_report(cases: list[dict]) -> dict:
    results = [run_case(case) for case in cases]
    return {
        "mode": "offline-fixture-fallback",
        "case_count": len(results),
        "metrics": {
            "poi_authority_rate": _average(results, "poi_authority_rate"),
            "field_reference_rate": _average(results, "field_reference_rate"),
            "time_conflict_rate": _average(results, "time_conflict_rate"),
            "route_violation_rate": _average(results, "route_violation_rate"),
            "attraction_duplicate_rate": _average(results, "attraction_duplicate_rate"),
            "budget_deviation_rate": _average(results, "budget_deviation_rate"),
            "success_status_rate": round(sum(r["status"] == "success" for r in results) / max(len(results), 1), 4),
            "degraded_status_rate": round(sum(r["status"] == "degraded" for r in results) / max(len(results), 1), 4),
            "failed_status_rate": round(sum(r["status"] == "failed" for r in results) / max(len(results), 1), 4),
            "fallback_success_rate": round(sum(r["fallback_success"] for r in results) / max(len(results), 1), 4),
            "trace_complete_rate": round(
                sum(
                    set(r["trace"]["nodes"]) >= {"parse", "research", "generate", "reflect", "format"}
                    and r["trace"]["tool_count"] >= 2
                    for r in results
                )
                / max(len(results), 1),
                4,
            ),
            "research_rounds_avg": _average(results, "research_rounds"),
            "research_pack_avg": _average(results, "research_pack"),
        },
        "details": results,
    }


def write_report(report: dict) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    metrics = report["metrics"]
    lines = [
        "# Agent 离线评测报告",
        "",
        "- 数据模式：固定权威 fixture + fallback 生成器（不依赖外部服务）",
        f"- 用例数：{report['case_count']}",
        "",
        "| 指标 | 结果 |",
        "| --- | ---: |",
    ]
    for key, value in metrics.items():
        lines.append(f"| {key} | {value:.2%} |")
    lines += [
        "",
        "| 城市 | 天数 | 权威 POI | 字段引用 | 冲突率 | 路线违规 | 重复率 | 预算偏差 | 轨迹工具数 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for result in report["details"]:
        case = result["case"]
        lines.append(
            f"| {case['city']} | {case['days']} | {result['poi_authority_rate']:.2%} | "
            f"{result['field_reference_rate']:.2%} | {result['time_conflict_rate']:.2%} | "
            f"{result['route_violation_rate']:.2%} | "
            f"{result['attraction_duplicate_rate']:.2%} | {result['budget_deviation_rate']:.2%} | "
            f"{result['trace']['tool_count']} |"
        )
    (REPORT_DIR / "report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="只运行前 N 个用例")
    parser.add_argument(
        "--cases", default=str(CASES_PATH), help="用例文件：默认 cases.json；主题化同题评测传 themed_cases.json"
    )
    args = parser.parse_args()
    cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    report = build_report(cases[: args.limit] if args.limit else cases)
    write_report(report)
    print(json.dumps(report["metrics"], ensure_ascii=False, indent=2))
    print(f"报告已生成：{REPORT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
