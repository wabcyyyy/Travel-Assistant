"""多 Agent 研究编排离线评测（固定 fixture，不依赖外部模型/网络）。

用法：
    uv run python tests/agent_eval/eval_research.py [--city 杭州]

内容：
- 按域评估三个研究 Agent 的证据质量（规模/置信度/推理轮次/降级/缺口）；
- 验证 Supervisor 缺口补查有效性（首轮景点证据为空 → 补查后证据可合并）。

评测走真实的 run_research / run_research_context / run_refill 链路，
仅把检索工具与 LLM 推理替换为确定性 fixture，结果可复现。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.agent import tools
from app.agent.research import (
    merge_candidates,
    reasoning,
    run_refill,
    run_research,
    run_research_context,
)
from app.agent.research.evidence import ResearchTask
from app.schemas.trip import GenerateRequest
from tests.agent_eval import mock_llm


def _research_patch():
    """研究链路注入：检索工具 + LLM 推理全部替换为确定性 fixture。"""
    return (
        patch.object(tools, "search_attractions", mock_llm.search_attractions),
        patch.object(tools, "search_foods", mock_llm.search_foods),
        patch.object(tools, "search_hotels", mock_llm.search_hotels),
        patch.object(tools, "get_consumption", mock_llm.get_consumption),
        patch.object(tools, "search_amap_poi", mock_llm.search_amap_poi),
        patch.object(reasoning, "plan_research", mock_llm.plan_research),
        patch.object(reasoning, "evaluate_research", mock_llm.evaluate_research),
    )


def run_domain_case(domain: str, city: str) -> dict:
    """单个研究域的证据质量快照。"""
    patches = _research_patch()
    for item in patches:
        item.start()
    try:
        pack = run_research(ResearchTask(domain=domain, city=city, limit=30))
    finally:
        for item in reversed(patches):
            item.stop()
    return {"domain": domain, "city": city, **pack.to_dict()}


def run_refill_case(city: str) -> dict:
    """Supervisor 补查有效性：首轮景点证据为空 → 补查后证据可合并。"""
    state = {"calls": 0}

    def search_attractions(city, preferences, limit=30):
        state["calls"] += 1
        if state["calls"] == 1:
            return []
        return [{"id": 1, "name": "补查景点", "category": "attraction",
                 "latitude": 30.0, "longitude": 120.0, "ticket_price": 40}]

    patches = _research_patch() + (patch.object(tools, "search_attractions", search_attractions),)
    for item in patches:
        item.start()
    try:
        req = GenerateRequest(city=city, days=1)
        context = run_research_context(req)
        first_round_empty = not context["candidates"]
        pack = run_refill("attraction", req)
        merged = merge_candidates(context["candidates"], pack.items)
        merged_names = {p.get("name") for p in merged}
        refill_filled = bool(merged) and "补查景点" in merged_names
    finally:
        for item in reversed(patches):
            item.stop()
    return {"city": city, "first_round_empty": first_round_empty,
            "refill_items": len(pack.items), "refill_filled": refill_filled}


def build_report(city: str = "杭州") -> dict:
    domains = [run_domain_case(domain, city) for domain in ("attraction", "food", "hotel")]
    refill = run_refill_case(city)
    total = max(len(domains), 1)
    return {
        "mode": "offline-fixture-research",
        "city": city,
        "domains": domains,
        "refill": refill,
        "metrics": {
            "avg_rounds": round(sum(d["rounds"] for d in domains) / total, 2),
            "pack_total": sum(d["count"] for d in domains),
            "degraded_rate": round(sum(1 for d in domains if d["degraded"]) / total, 2),
            "refill_effectiveness": 1.0 if refill["refill_filled"] else 0.0,
        },
    }


def write_report(report: dict) -> None:
    report_dir = Path(__file__).with_name("report")
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "research_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# 多 Agent 研究编排评测报告", "",
        f"- 城市：{report['city']}",
        "- 数据模式：固定权威 fixture + 确定性 LLM 推理（不依赖外部服务）", "",
        "| 域 | 证据数 | 置信度 | 轮次 | 降级 | 缺口 |",
        "| --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for domain in report["domains"]:
        lines.append(
            f"| {domain['domain']} | {domain['count']} | {domain['confidence']} | "
            f"{domain['rounds']} | {domain['degraded']} | {'；'.join(domain['gaps']) or '-'} |")
    lines.append("")
    lines.append(f"- 补查有效性：首轮景点证据为空 = {report['refill']['first_round_empty']}；"
                 f"补查后证据可合并 = {report['refill']['refill_filled']}")
    lines.append(f"- 指标：平均推理轮次 {report['metrics']['avg_rounds']}，"
                 f"证据总量 {report['metrics']['pack_total']}，"
                 f"降级率 {report['metrics']['degraded_rate']}，"
                 f"补查有效率 {report['metrics']['refill_effectiveness']}")
    (report_dir / "research_report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--city", default="杭州")
    args = parser.parse_args()
    report = build_report(args.city)
    write_report(report)
    print(json.dumps(report["metrics"], ensure_ascii=False, indent=2))
    print(f"报告已生成：{Path(__file__).with_name('report')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
