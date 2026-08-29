from app.agent.chat_draft import (
    HotelIntent,
    _apply_decision_patches,
    _apply_plan_update,
    _decision_reply,
    _dedupe_plans,
    _deterministic_reduce,
    _fallback_hotel_intent,
    _increase_target_days,
    _is_vague_poi_browse_request,
    _hotel_comparison_base_tier,
    _plan_conflict,
    _reduce_target_days,
    _requested_day_count,
    _substantive_plan_signature,
    _with_stay_scope,
)
from app.schemas.trip import ChatTurnRequest


def _request(message: str) -> ChatTurnRequest:
    return ChatTurnRequest(
        city="杭州",
        days=2,
        persons=2,
        plans=[
            {
                "day_no": 1,
                "note": "第一天",
                "items": [
                    {
                        "id": 1,
                        "item_type": "attraction",
                        "poi_name": "苏堤春晓",
                        "start_time": "08:30",
                        "end_time": "10:00",
                        "duration_min": 90,
                    },
                    {
                        "id": 2,
                        "item_type": "hotel",
                        "poi_name": "杭州西子宾馆汪庄",
                        "start_time": "20:00",
                        "duration_min": 30,
                    },
                ],
            },
            {
                "day_no": 2,
                "note": "第二天",
                "items": [
                    {
                        "id": 3,
                        "item_type": "attraction",
                        "poi_name": "灵隐寺",
                        "start_time": "07:00",
                        "end_time": "09:00",
                        "duration_min": 120,
                    }
                ],
            },
        ],
        message=message,
    )


def test_vague_poi_browse_does_not_imply_mutation():
    assert _is_vague_poi_browse_request("我想看看其他景点")
    assert not _is_vague_poi_browse_request("用岳王庙替换这个景点")


def test_time_update_recalculates_end_time():
    request = _request("把苏堤春晓改到下午三点")
    plans = _apply_decision_patches(
        {"target_days": None, "patches": [{"op": "update", "item_id": 1, "fields": {"start_time": "15:00"}}]},
        request,
    )
    item = next(item for item in plans[0]["items"] if item["id"] == 1)
    assert item["end_time"] == "16:30"


def test_unrequested_delete_is_ignored_when_extending_trip():
    request = _request("改成3天")
    plans = _apply_decision_patches(
        {
            "target_days": 3,
            "patches": [
                {"op": "delete", "item_id": 1},
                {"op": "move", "item_id": 3, "day_no": 3},
            ],
        },
        request,
    )
    assert any(item.get("id") == 1 for plan in plans for item in plan["items"])


def test_moved_item_is_rescheduled_when_original_time_conflicts():
    request = _request("把灵隐寺移到第一天")
    plans = _apply_decision_patches(
        {"target_days": None, "patches": [{"op": "move", "item_id": 3, "day_no": 1}]},
        request,
    )
    moved = next(item for item in plans[0]["items"] if item.get("id") == 3)
    assert moved["start_time"] == "10:00"
    assert moved["end_time"] == "12:00"


def test_conflict_and_note_only_change_are_detectable():
    request = _request("调整一下")
    changed_notes = [dict(plan, note="新备注") for plan in request.plans]
    assert _substantive_plan_signature(changed_notes) == _substantive_plan_signature(request.plans)
    conflict_plans = [{"day_no": 1, "items": [
        {"item_type": "attraction", "poi_name": "甲", "start_time": "09:00", "end_time": "11:00"},
        {"item_type": "food", "poi_name": "乙", "start_time": "10:30", "end_time": "12:00"},
    ]}]
    assert _plan_conflict(conflict_plans) == (1, "甲", "乙")


def test_placeholder_reply_and_generic_hotel_change_are_normalized():
    assert _decision_reply("中文Markdown", "安全回复") == "安全回复"
    assert _fallback_hotel_intent("给我换酒店", "豪华型").action == "same"


def test_unspecified_hotel_scope_defaults_to_all_existing_nights():
    request = _request("换个酒店")
    request.plans[1]["items"].append({
        "id": 4, "item_type": "hotel", "poi_name": "杭州西子宾馆汪庄",
    })
    intent = _with_stay_scope(HotelIntent("same", "奢华型", "奢华型"), request, [])
    assert intent.requested_nights == 2
    assert intent.requested_day_nos == (1, 2)


def test_numbered_night_is_not_misread_as_night_count():
    request = _request("第二晚换酒店")
    request.plans[1]["items"].append({
        "id": 4, "item_type": "hotel", "poi_name": "杭州西子宾馆汪庄",
    })
    intent = _with_stay_scope(HotelIntent("same", "奢华型", "奢华型"), request, [])
    assert not intent.invalid_scope
    assert intent.requested_nights == 1
    assert intent.requested_day_nos == (2,)


def test_only_explicit_continuation_uses_previous_proposed_tier():
    request = _request("再便宜一点")
    request.history = [{
        "role": "ai",
        "content": "你当前是奢华型，本次提供 **3 家豪华型酒店** 供比较。",
    }]
    assert _hotel_comparison_base_tier(request, []) == "豪华型"
    request.message = "看看其他酒店"
    assert _hotel_comparison_base_tier(request, []) == "舒适型"


def test_explicit_new_hotel_day_can_target_day_without_existing_hotel():
    request = _request("第五天住四季")
    request.days = 5
    request.plans.extend([
        {"day_no": 3, "items": []},
        {"day_no": 4, "items": []},
        {"day_no": 5, "items": []},
    ])
    intent = _with_stay_scope(HotelIntent("specific", "奢华型", "奢华型"), request, [])
    assert not intent.invalid_scope
    assert intent.requested_day_nos == (5,)


def test_reduce_by_days_is_parsed_as_subtraction():
    # “减少 2 天”应理解为在现有天数上减去 2 天，而不是改成 2 天。
    assert _requested_day_count("减少2天", current_days=5) == 3
    assert _requested_day_count("缩短一天", current_days=5) == 4
    # 范围表述取首个数字做保守减量，不再误判成“改成 2 天”。
    assert _requested_day_count("减少一两天的行程", current_days=5) == 4
    # “改成 N 天”仍按目标天数解析。
    assert _requested_day_count("改成3天", current_days=5) == 3


def test_reduce_target_days_only_for_reduce_by_phrase():
    request = _request("减少一些重复景点")
    assert _reduce_target_days(request) is None
    request.message = "缩短2天"
    request.days = 5
    assert _reduce_target_days(request) == 3


def test_deterministic_reduce_removes_cross_day_duplicates():
    request = _request("帮我减少一些重复景点")
    request.plans[0]["items"].append({
        "id": 5, "item_type": "attraction", "poi_name": "灵隐寺",
        "start_time": "13:00", "end_time": "15:00",
    })
    plans = _deterministic_reduce(request)
    names = [it.get("poi_name") for plan in plans for it in plan["items"]
             if it.get("item_type") == "attraction"]
    assert names.count("灵隐寺") == 1
    # 酒店不受影响。
    assert any(it.get("poi_name") == "杭州西子宾馆汪庄" for plan in plans for it in plan["items"])


def test_deterministic_reduce_shortens_days():
    request = _request("缩短2天")
    request.days = 5
    request.plans = [
        {"day_no": d, "note": f"第{d}天", "items": [
            {"id": d, "item_type": "attraction", "poi_name": f"景点{d}", "start_time": "09:00", "end_time": "11:00"},
        ]}
        for d in range(1, 6)
    ]
    plans = _deterministic_reduce(request, target_days=3)
    assert [p["day_no"] for p in plans] == [1, 2, 3]


def test_add_day_is_parsed_as_increase_by():
    # “加一天/增加两天”应理解为在现有天数上加上 N 天，而不是改成 1 天。
    assert _requested_day_count("我想再加一天行程", current_days=5) == 6
    assert _requested_day_count("增加两天", current_days=5) == 7
    assert _increase_target_days(_request("加一天")) == 3  # 固定夹具 days=2 → 2+1=3
    # extension_requested 在 run_chat_turn 里正是用 _increase_target_days(req) is not None 判定
    assert _increase_target_days(_request("延长一天行程")) == 3
    assert _increase_target_days(_request("减少一些景点")) is None


def test_dedupe_plans_removes_cross_day_duplicates_without_touching_hotels():
    plans = [
        {"day_no": 1, "items": [
            {"item_type": "attraction", "poi_name": "A", "start_time": "09:00", "end_time": "10:00"},
            {"item_type": "hotel", "poi_name": "H"},
        ]},
        {"day_no": 2, "items": [
            {"item_type": "attraction", "poi_name": "A", "start_time": "09:00", "end_time": "10:00"},
            {"item_type": "food", "poi_name": "B", "start_time": "12:00", "end_time": "13:00"},
        ]},
    ]
    out = _dedupe_plans(plans)
    names = [it["poi_name"] for p in out for it in p["items"]]
    assert names.count("A") == 1
    assert "H" in names
    assert "B" in names


def test_rewrite_plan_routes_full_document():
    # “减少一天并重新安排景点”这类大改应走 rewrite_plan，模型返回完整 plan_document，
    # 由 _extract_document_plans 安全落地（保留项带原 id、删除项不写入）。
    request = _request("减少一天并重新安排景点")  # 夹具 days=2 → 目标 1 天
    decision = {
        "mode": "rewrite_plan",
        "plan_document": {
            "schema_version": 1,
            "trip": {"city": "杭州", "days": 1, "persons": 2, "budget": None,
                     "start_date": None, "end_date": None, "preferences": [], "hotel_tier": None},
            "days": [{
                "day_no": 1, "note": "第一天",
                "items": [{"id": 1, "item_type": "attraction", "poi_name": "苏堤春晓",
                           "start_time": "08:30", "end_time": "10:00", "duration_min": 90}],
            }],
        },
    }
    plans = _apply_plan_update(decision, request)
    assert plans is not None
    assert len(plans) == 1
    assert plans[0]["items"][0]["poi_name"] == "苏堤春晓"


def test_plan_update_still_routes_patches():
    # 小修小补仍走 patches 补丁路径，不受 rewrite_plan 影响。
    request = _request("把苏堤春晓改到下午三点")
    decision = {"mode": "plan_update",
                "patches": [{"op": "update", "item_id": 1, "fields": {"start_time": "15:00"}}]}
    plans = _apply_plan_update(decision, request)
    assert plans is not None
    item = next(it for p in plans for it in p["items"] if it.get("id") == 1)
    assert item["start_time"] == "15:00"
