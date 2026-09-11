"""行程生成质量评测：自实现的 RAGAS 风格指标（P1②）。

与 evaluation.py（检索离线指标）互补，评测对象是"引用式生成"链路
（开放模式 + 权威参考资料注入）。指标分两类：

确定性指标（来自 ReferencePool 统计，无 LLM 参与）：
- citation_coverage 引用覆盖率：行程项被权威参考资料背书（名称或 refs 命中）
  的比例，衡量生成结果对权威知识库的 grounding 程度；
- citation_validity 引用有效率：携带 refs 的行程项中，编号能解析到真实
  参考条目的比例，衡量模型引用行为的可靠性；
- context_utilization 资料利用率：参考资料被至少一个行程项命中的比例，
  衡量检索出的 top-K 对生成是否有实际贡献。

LLM-as-judge 指标：
- faithfulness 忠实度：从生成的行程中抽取事实性声明，逐条对照参考资料
  判断是否被支持（RAGAS faithfulness 的行程版单调用实现）。

judge 与 generate_fn 均通过参数注入：离线测试注入假实现；真实评测使用
LLMClient 与 workflow._generate_open_plans 主链路。命令行直接运行本模块
可对 6 个知识库城市执行真实评测并输出报告。
"""

from __future__ import annotations

import json
import sys
import time
from typing import Any, Callable

from app.agent.day_stream import run_plan_context
from app.agent.generators import ReferencePool
from app.agent.trace import record_event

JudgeFn = Callable[[str, str], list[dict[str, Any]]]

JUDGE_SYSTEM_PROMPT = (
    "你是行程事实核查评测员。对照权威参考资料，抽取行程中可验证的事实性声明"
    "（价格、开放时间、地点属性、描述中的事实断言），逐条判断参考资料是否支持该声明。"
    "规则：与参考资料一致的声明为 supported；参考资料未覆盖、无法核实的声明为 "
    "unsupported；模型自述的估算值（remark 含“估算/供参考/以现场为准”）不抽取；"
    "时间安排、顺序、预算等规划性内容不是事实声明，不抽取。"
    "只输出 JSON：{\"claims\":[{\"text\":\"声明内容\",\"supported\":true或false,"
    "\"evidence\":\"支持的参考资料编号 R3 或 null\"}]}"
)


def reference_metrics(stats: dict[str, Any]) -> dict[str, float]:
    """从 ReferencePool.stats 解析确定性引用指标；无行程项时各项记 1.0。"""
    total = int(stats.get("items") or 0)
    grounded = int(stats.get("grounded") or 0)
    refs_cited = int(stats.get("refs_cited") or 0)
    refs_valid = int(stats.get("refs_valid") or 0)
    references = int(stats.get("references") or 0)
    cited = int(stats.get("cited_references") or 0)
    return {
        "citation_coverage": round(grounded / total, 4) if total else 1.0,
        "citation_validity": round(refs_valid / refs_cited, 4) if refs_cited else 1.0,
        "context_utilization": round(cited / references, 4) if references else 1.0,
    }


def faithfulness_score(plans: list[dict], reference_block: str, judge: JudgeFn) -> float:
    """忠实度：judge 抽取声明并判断支持率；无声明时记 1.0。

    judge(references_block, plans_json) -> [{"text":..., "supported": bool}, ...]
    异常视为评测失败而非生成失败，抛出交由调用方处理。
    """
    claims = judge(reference_block, json.dumps(plans, ensure_ascii=False, default=str))
    supported = sum(1 for claim in claims if claim.get("supported") is True)
    return round(supported / len(claims), 4) if claims else 1.0


def default_judge(reference_block: str, plans_json: str) -> list[dict[str, Any]]:
    """默认 LLM judge：使用应用配置的 OpenAI 兼容客户端。"""
    from app.common.llm_client import get_llm_client

    raw = get_llm_client().complete(
        f"权威参考资料：\n{reference_block}\n\n行程：\n{plans_json}",
        system_prompt=JUDGE_SYSTEM_PROMPT,
        temperature=0.0,
        max_tokens=2000,
        json_mode=True,
    )
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("judge 输出中未找到 JSON")
    claims = json.loads(raw[start:end + 1]).get("claims")
    return claims if isinstance(claims, list) else []


def evaluate_generation(plans: list[dict], *, reference_stats: dict[str, Any],
                        reference_block: str, judge: JudgeFn | None = None) -> dict[str, float]:
    """评测一次引用式生成的全部指标；无参考资料时跳过 faithfulness。"""
    metrics = reference_metrics(reference_stats)
    if reference_stats.get("references"):
        metrics["faithfulness"] = faithfulness_score(
            plans, reference_block, judge or default_judge)
    return metrics


def aggregate_generation_metrics(results: list[dict[str, float]]) -> dict[str, float]:
    """按指标键求均值；faithfulness 缺失的 case 不计入该键。"""
    if not results:
        return {}
    keys = {key for result in results for key in result if isinstance(result[key], (int, float))}
    return {key: round(sum(float(result[key]) for result in results if key in result)
                       / max(sum(1 for result in results if key in result), 1), 4)
            for key in sorted(keys)}


def run_generation_case(city: str, *, days: int = 2, persons: int = 2,
                        budget: float | None = None, preferences: list[str] | None = None,
                        requirements: str | None = None,
                        judge: JudgeFn | None = None) -> dict[str, Any]:
    """对单个城市执行一次真实评测：检索上下文 → 开放模式引用式生成 → 指标。"""
    from app.schemas.trip import GenerateRequest

    from app.agent.workflow import _generate_open_plans

    preferences = preferences or []
    context = run_plan_context(city, preferences)
    req = GenerateRequest(city=city, days=days, persons=persons, budget=budget,
                          preferences=preferences, requirements=requirements)
    started = time.monotonic()
    state = _generate_open_plans(req, "", context.get("hotels"),
                                 candidates=context.get("candidates"),
                                 foods=context.get("foods"))
    duration_ms = int((time.monotonic() - started) * 1000)
    if state is None:
        return {"city": city, "error": "open_research_failed", "duration_ms": duration_ms}
    plans = state.get("daily_plans") or []
    stats = (state.get("schedule_report") or {}).get("reference_stats") or {}
    pool = ReferencePool(context)
    metrics = evaluate_generation(plans, reference_stats=stats,
                                  reference_block=pool.block(), judge=judge)
    record_event("evaluation", "generation_case", metadata={"city": city, **metrics})
    return {"city": city, "days": days, "metrics": metrics,
            "reference_stats": stats, "duration_ms": duration_ms}


DEFAULT_CITIES = ("北京", "上海", "成都", "西安", "三亚", "杭州")


def main() -> int:
    """真实评测入口：python -m app.rag.evaluation_generation [城市...]"""
    cities = sys.argv[1:] or list(DEFAULT_CITIES)
    results = [run_generation_case(city) for city in cities]
    ok = [result for result in results if "metrics" in result]
    report = {
        "cases": results,
        "aggregate": aggregate_generation_metrics(
            [result["metrics"] for result in ok]),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
