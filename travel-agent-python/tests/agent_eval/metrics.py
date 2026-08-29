"""Agent 评测指标：把“能生成”拆成可回答面试追问的质量指标。"""

from __future__ import annotations

from collections import Counter
from app.agent.reflect import _item_end, _item_start, estimate_transfer_minutes


def _items(response) -> list[dict]:
    return [item.model_dump() if hasattr(item, "model_dump") else item
            for plan in response.daily_plans
            for item in plan.items]


def evaluate_response(response, case: dict, catalog: dict, trace: dict) -> dict:
    items = _items(response)
    all_known = {p["name"]: p for p in catalog["attractions"] + catalog["foods"] + catalog["hotels"]}
    poi_items = [i for i in items if i.get("item_type") in ("attraction", "food", "hotel")]
    authoritative = [i for i in poi_items if i.get("poi_name") in all_known]
    field_matches = []
    for item in authoritative:
        source = all_known[item["poi_name"]]
        if item.get("item_type") in ("attraction", "food"):
            field_matches.append(item.get("cost") == source.get("ticket_price"))
    field_reference_rate = sum(field_matches) / len(field_matches) if field_matches else 1.0

    conflicts = 0
    pairs = 0
    route_violations = 0
    route_pairs = 0
    duplicates = Counter()
    attractions = []
    for plan in response.daily_plans:
        timed = [i for i in plan.items if i.item_type in ("attraction", "food")]
        timed = sorted((i.model_dump() for i in timed), key=_item_start)
        pairs += max(len(timed) - 1, 0)
        for i in range(len(timed) - 1):
            previous, following = timed[i], timed[i + 1]
            previous_end = _item_end(previous)
            following_start = _item_start(following)
            conflicts += previous_end > following_start
            required = estimate_transfer_minutes(previous, following)
            if required is not None:
                route_pairs += 1
                route_violations += following_start >= previous_end and following_start - previous_end < required
        attractions.extend(i.poi_name for i in plan.items if i.item_type == "attraction")
    duplicates.update(attractions)
    duplicate_count = sum(n - 1 for n in duplicates.values() if n > 1)

    cons = catalog["consumption"]
    rooms = (case["persons"] + 1) // 2
    selected_ticket = sum(float(i.get("cost") or 0) for i in items if i.get("item_type") == "attraction")
    selected_hotel = sum(float(i.get("cost") or 0) for i in items if i.get("item_type") == "hotel")
    expected = {
        "门票": round(selected_ticket * case["persons"], 2),
        "餐饮": round(float(cons.get("meal_price", 60)) * 2 * case["days"] * case["persons"], 2),
        "交通": round(float(cons.get("transport_price", 35)) * case["days"] * case["persons"], 2),
        "酒店": round(selected_hotel * rooms, 2),
    }
    expected_total = sum(expected.values())
    actual_total = sum(float(v) for v in response.budget_estimate.values())

    tool_events = [event for event in trace.get("events", []) if event["kind"] == "tool"]
    node_events = [event for event in trace.get("events", []) if event["kind"] == "node"]
    return {
        "case": case,
        "status": response.status,
        "status_reason": response.status_reason,
        "days": len(response.daily_plans),
        "total_items": len(items),
        "poi_authority_rate": round(len(authoritative) / max(len(poi_items), 1), 4),
        "field_reference_rate": round(field_reference_rate, 4),
        "time_conflict_rate": round(conflicts / pairs, 4) if pairs else 0.0,
        "route_violation_rate": round(route_violations / route_pairs, 4) if route_pairs else 0.0,
        "attraction_duplicate_rate": round(duplicate_count / max(len(attractions), 1), 4),
        "budget_deviation_rate": round(abs(actual_total - expected_total) / expected_total, 4)
        if expected_total else 0.0,
        "fallback_success": len(response.daily_plans) == case["days"] and all(plan.items for plan in response.daily_plans),
        "trace": {
            "node_count": len(node_events),
            "tool_count": len(tool_events),
            "nodes": [event["name"] for event in node_events],
            "tools": [event["name"] for event in tool_events],
            "routes": [event["name"] for event in trace.get("events", []) if event["kind"] == "route"],
        },
    }
