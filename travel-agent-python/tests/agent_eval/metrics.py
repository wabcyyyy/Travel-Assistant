"""Agent 评测指标：把“能生成”拆成可回答面试追问的质量指标。"""

from __future__ import annotations

from collections import Counter

from app.agent.intent import build_intent_keywords
from app.agent.reflect import _item_end, _item_start, estimate_transfer_minutes


def _items(response) -> list[dict]:
    return [
        item.model_dump() if hasattr(item, "model_dump") else item
        for plan in response.daily_plans
        for item in plan.items
    ]


def _has_coord(value) -> bool:
    """坐标有效：非 None 且非 0（0/0 是缺失哨兵，与生成链路 _has_coord 口径一致）。"""
    try:
        return value is not None and abs(float(value)) > 1e-6
    except (TypeError, ValueError):
        return False


def evaluate_narrative(response, case: dict) -> dict:
    """M5 叙事化指标：度量契约 v1.1.narrative 叙事字段的质量与意图贴合度。

    与 evaluate_response（权威/冲突/预算口径）互补，只读叙事层字段，不改
    既有函数签名。各指标定义：
    - theme_sentence_rate：每日 theme 是叙事句（非空且非「A→B→C」纯路径串，
      即不含 "→"）的比例；
    - why_coverage：attraction 项 why_this 非空的比例；
    - practical_notes_rate：每日 practical_notes 非空的比例；
    - theme_hit_rate：意图关键词（build_intent_keywords(case.intent)）在
      （trip_theme + 各日 theme + 全部 why_this + remark）拼接文本中的
      命中关键词占比；case 无 intent 时为 None；
    - poi_relevance：attraction 项中 why_this/remark 命中任一意图关键词的
      比例（「主题相关点占比」）；case 无 intent 时为 None；
    - coord_available_rate：attraction 项坐标非空（lat/lon 均非 None 非 0）
      的比例；
    - pending_review_count：verification_status=="unverified" 的 item 数
      （「待复核占比」的分子）。
    """
    keywords = build_intent_keywords(case.get("intent"))
    plans = list(response.daily_plans)
    items = _items(response)
    attractions = [i for i in items if i.get("item_type") == "attraction"]

    theme_sentence_days = sum(1 for plan in plans if plan.theme and "→" not in plan.theme)
    practical_days = sum(1 for plan in plans if plan.practical_notes)
    why_filled = sum(1 for i in attractions if (i.get("why_this") or "").strip())
    coord_ok = sum(1 for i in attractions if _has_coord(i.get("latitude")) and _has_coord(i.get("longitude")))
    pending_review = sum(1 for i in items if i.get("verification_status") == "unverified")

    theme_hit_rate = None
    poi_relevance = None
    if keywords:
        # 关键词命中语料：行程级主题 + 每日主题 + 全部条目的 why_this/remark
        corpus = [response.trip_theme or ""]
        corpus += [plan.theme or "" for plan in plans]
        corpus += [(i.get("why_this") or "") + (i.get("remark") or "") for i in items]
        text = "".join(corpus)
        theme_hit_rate = sum(1 for k in keywords if k in text) / len(keywords)
        poi_relevance = sum(
            1 for i in attractions if any(k in (i.get("why_this") or "") + (i.get("remark") or "") for k in keywords)
        ) / max(len(attractions), 1)

    return {
        "theme_sentence_rate": round(theme_sentence_days / max(len(plans), 1), 4),
        "why_coverage": round(why_filled / max(len(attractions), 1), 4),
        "practical_notes_rate": round(practical_days / max(len(plans), 1), 4),
        "theme_hit_rate": round(theme_hit_rate, 4) if theme_hit_rate is not None else None,
        "poi_relevance": round(poi_relevance, 4) if poi_relevance is not None else None,
        "coord_available_rate": round(coord_ok / max(len(attractions), 1), 4),
        "pending_review_count": pending_review,
    }


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
    # 住宿期望与生产口径一致：N 天 = N-1 晚，最后一天不计房价。
    selected_hotel = sum(
        float(i.cost or 0)
        for plan in response.daily_plans
        if plan.day_no < case["days"]
        for i in plan.items
        if i.item_type == "hotel"
    )
    # 餐饮期望与生产口径一致：有价日期按实际选中餐厅人均价×2 餐，
    # 无价日期回落到城市人均餐价×2；否则指标会惩罚"高价餐厅如实计价"这一有意改进。
    priced_meal = 0.0
    priced_days = 0
    for plan in response.daily_plans:
        day_meal = max(
            (float(i.cost or 0) for i in plan.items if i.item_type == "food" and i.cost is not None), default=0.0
        )
        if day_meal > 0:
            priced_meal += day_meal * 2
            priced_days += 1
    unpriced_days = max(case["days"] - priced_days, 0)
    expected = {
        "门票": round(selected_ticket * case["persons"], 2),
        "餐饮": round(
            priced_meal * case["persons"] + float(cons.get("meal_price", 60)) * 2 * unpriced_days * case["persons"], 2
        ),
        "交通": round(float(cons.get("transport_price", 35)) * case["days"] * case["persons"], 2),
        "酒店": round(selected_hotel * rooms, 2),
    }
    expected_total = sum(expected.values())
    actual_total = sum(float(v) for v in response.budget_estimate.values())

    tool_events = [event for event in trace.get("events", []) if event["kind"] == "tool"]
    node_events = [event for event in trace.get("events", []) if event["kind"] == "node"]
    # 多 Agent 研究编排（P3）：从 schedule_report 汇总各域证据包规模与推理轮次。
    research = (response.schedule_report or {}).get("research") or {}
    research_agents = research.get("agents") or {}
    research_rounds = sum((a or {}).get("rounds", 0) for a in research_agents.values())
    research_pack = sum((a or {}).get("count", 0) for a in research_agents.values())
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
        if expected_total
        else 0.0,
        "fallback_success": len(response.daily_plans) == case["days"]
        and all(plan.items for plan in response.daily_plans),
        "trace": {
            "node_count": len(node_events),
            "tool_count": len(tool_events),
            "nodes": [event["name"] for event in node_events],
            "tools": [event["name"] for event in tool_events],
            "routes": [event["name"] for event in trace.get("events", []) if event["kind"] == "route"],
        },
        "research_rounds": research_rounds,
        "research_pack": research_pack,
    }
