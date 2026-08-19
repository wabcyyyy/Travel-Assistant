"""Agent 质量量化评测套件（D4 可复现：fallback 确定性生成，无需 LLM key）。

运行方式：
  uv run python tests/eval/eval_agent.py [case_count] [--full]
默认跑 5 个用例（快速冒烟），--full 跑 30 个用例。
输出 tests/eval/report/report.json 与 report.md
指标公式（与开发计划 D4 对齐）：
  工具调用准确率 = 正确检索(景点/餐饮来自知识库) / 全部检索
  时间冲突率     = 同日相邻项时间重叠对数 / 同日相邻项总对数
  景点重复率     = 重复出现的景点次数 / 全部景点出现次数
  预算偏差率     = |估算预算 - 参考预算| / 参考预算
  幻觉检出率     = 检出虚假景点数 / 输出景点总数
"""
import json
import sys
from collections import Counter
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))

import httpx

from app.agent import poi_repository
from app.agent.reflect import parse_time, _item_end, _item_start

AGENT_URL = "http://127.0.0.1:8000"

CITIES = ["北京", "上海", "广州", "成都", "西安"]
PREFERENCES = ["亲子", "人文", "美食", "自然", "网红"]

PRICE_DEVIATION_THRESHOLD = 0.30


def reference_budget(city: str, days: int, persons: int) -> dict:
    from math import ceil

    cons = poi_repository.get_city_consumption(city) or {}
    attrs = poi_repository.search_pois(city, category="attraction", limit=30)
    ticket = (sum(float(a.get("ticket_price") or 0) for a in attrs) / max(len(attrs), 1)) * 3
    meal = float(cons.get("meal_price", 60.0)) * 2
    transport = float(cons.get("transport_price", 35.0))
    hotel = float(cons.get("hotel_price", 300.0))
    rooms = ceil(persons / 2)
    return {"门票": round(ticket * persons, 2),
            "餐饮": round(meal * days * persons, 2),
            "交通": round(transport * days * persons, 2),
            "酒店": round(hotel * rooms * days, 2)}


def _to_snake(item: dict) -> dict:
    return {
        "item_type": item.get("itemType"),
        "poi_name": item.get("poiName"),
        "start_time": item.get("startTime"),
        "end_time": item.get("endTime"),
        "duration_min": item.get("durationMin"),
        "cost": item.get("cost"),
    }


def build_cases(count: int) -> list[dict]:
    cases = []
    i = 0
    combos = [(d, p) for d in (1, 2, 3) for p in PREFERENCES]
    for city in CITIES:
        for j in range(count // len(CITIES)):
            days, pref = combos[(i * 7 + j) % len(combos)]
            cases.append({"city": city, "days": days, "pref": pref, "persons": 2})
            i += 1
    return cases[:count]


def evaluate_one(client: httpx.Client, case: dict) -> dict:
    resp = client.post("/api/agent/v1/generate", json={
        "city": case["city"], "days": case["days"], "persons": case["persons"],
        "budget": 5000, "preferences": [case["pref"]],
    })
    body = resp.json()
    assert body["code"] == 200, body
    data = body["data"]
    plans = data["dailyPlans"]

    kb = poi_repository.search_pois(case["city"], limit=200)
    kb_names = {p["name"] for p in kb}
    kb_by_name = {p["name"]: p for p in kb}
    cons = poi_repository.get_city_consumption(case["city"]) or {}

    items = [it for plan in plans for it in plan["items"]]
    attractions = [it for it in items if it["itemType"] == "attraction"]
    foods = [it for it in items if it["itemType"] == "food"]

    tool_calls = len(attractions) + len(foods)
    correct_calls = sum(1 for it in attractions + foods if it["poiName"] in kb_names)
    tool_accuracy = correct_calls / tool_calls if tool_calls else 1.0

    conflicts = 0
    adjacent_pairs = 0
    for plan in plans:
        timed = [_to_snake(it) for it in plan["items"] if it["itemType"] in ("attraction", "food")]
        timed.sort(key=_item_start)
        adjacent_pairs += max(len(timed) - 1, 0)
        for i in range(len(timed) - 1):
            if _item_end(timed[i]) > _item_start(timed[i + 1]):
                conflicts += 1
    conflict_rate = conflicts / adjacent_pairs if adjacent_pairs else 0.0

    name_counter = Counter(it["poiName"] for it in attractions)
    dup_count = sum(c - 1 for c in name_counter.values() if c > 1)
    dup_rate = dup_count / max(len(attractions), 1)

    ref = reference_budget(case["city"], case["days"], case["persons"])
    est = {k: float(v) for k, v in data["budgetEstimate"].items()}
    ref_total = sum(ref.values())
    est_total = sum(est.values())
    budget_deviation = abs(est_total - ref_total) / ref_total if ref_total else 0.0

    hallucinations = []
    for it in attractions:
        if it["poiName"] not in kb_names:
            hallucinations.append({"name": it["poiName"], "reason": "不在知识库"})
            continue
        ref_price = kb_by_name[it["poiName"]].get("ticket_price")
        cost = it.get("cost")
        if ref_price and cost is not None:
            deviation = abs(cost - float(ref_price)) / float(ref_price)
            if deviation > PRICE_DEVIATION_THRESHOLD:
                hallucinations.append({"name": it["poiName"],
                                       "reason": f"价格偏差 {deviation:.1%}（库内 {ref_price}，输出 {cost}）"})
    hallucination_rate = len(hallucinations) / max(len(attractions), 1)

    return {
        "case": case,
        "days": len(plans),
        "totalItems": len(items),
        "toolAccuracy": round(tool_accuracy, 4),
        "conflictRate": round(conflict_rate, 4),
        "dupRate": round(dup_rate, 4),
        "budgetDeviation": round(budget_deviation, 4),
        "hallucinationRate": round(hallucination_rate, 4),
        "hallucinations": hallucinations,
    }


def main() -> int:
    full = "--full" in sys.argv
    count = 30 if full else 5
    cases = build_cases(count)
    results = []
    with httpx.Client(base_url=AGENT_URL, timeout=60.0) as client:
        for i, case in enumerate(cases, 1):
            print(f"[{i}/{len(cases)}] {case['city']} {case['days']}天 {case['pref']} ...", end=" ", flush=True)
            r = evaluate_one(client, case)
            results.append(r)
            print(f"toolAcc={r['toolAccuracy']} conflict={r['conflictRate']} dup={r['dupRate']} "
                  f"budgetDev={r['budgetDeviation']} halluc={r['hallucinationRate']}")

    def avg(key):
        return round(sum(r[key] for r in results) / len(results), 4) if results else 0.0

    summary = {
        "caseCount": len(results),
        "toolCallAccuracy": avg("toolAccuracy"),
        "timeConflictRate": avg("conflictRate"),
        "attractionDuplicateRate": avg("dupRate"),
        "budgetDeviationRate": avg("budgetDeviation"),
        "hallucinationRate": avg("hallucinationRate"),
        "details": results,
    }

    out_dir = Path(__file__).parent / "report"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Agent 质量评测报告",
        "",
        f"- 用例数：{len(results)}（fallback 确定性模式，temperature 固定，无 LLM key 可复现）",
        f"- 工具调用准确率：{summary['toolCallAccuracy']:.2%}",
        f"- 时间冲突率：{summary['timeConflictRate']:.2%}",
        f"- 景点重复率：{summary['attractionDuplicateRate']:.2%}",
        f"- 预算偏差率：{summary['budgetDeviationRate']:.2%}",
        f"- 幻觉检出率：{summary['hallucinationRate']:.2%}",
        "",
        "| 用例 | 城市 | 天数 | 偏好 | 工具准确率 | 冲突率 | 重复率 | 预算偏差 | 幻觉率 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in results:
        c = r["case"]
        lines.append(
            f"| {c['city']}{c['days']}天{c['pref']} | {c['city']} | {c['days']} | {c['pref']} | "
            f"{r['toolAccuracy']:.2%} | {r['conflictRate']:.2%} | {r['dupRate']:.2%} | "
            f"{r['budgetDeviation']:.2%} | {r['hallucinationRate']:.2%} |"
        )
        for h in r["hallucinations"]:
            lines.append(f"  - 幻觉项：{h['name']}（{h['reason']}）")
    (out_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")

    print(f"\n报告已生成：{out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())