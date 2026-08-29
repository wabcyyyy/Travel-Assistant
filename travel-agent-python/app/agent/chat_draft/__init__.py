"""chat_draft：把用户自然语言改行程的请求，产出一份可确认的安全草稿。

本包是原先单文件 chat_draft.py 的拆分结果，按“关注点”分为：
intent（意图/天数解析）、validate（安全校验）、document（JSON 投影与补水）、
plan_edit（编辑执行层）、hotel（酒店子系统）、decide（编排与对外入口）。

对外只暴露 run_chat_turn（供 app/api/agent.py 调用）以及若干内部辅助函数，
保持与原 chat_draft 模块相同的导入兼容。核心范式：LLM 当规划者产出结构化意图，
确定性代码当执行者落地并校验，最终由前端确认后才落库。"""

# 兼容旧导入：chat_draft 现在是一个包，对外只暴露 run_chat_turn 与内部辅助函数。
from .decide import (_decide_plan_change, run_chat_turn)
from .hotel import (HotelIntent, _HOTEL_BRAND_ALIASES, _INTENT_LABELS, _TIER_ALIASES, _TIER_KEYWORDS, _TIER_RANK, _available_hotel_day_nos, _current_hotel_names, _current_hotel_tier, _explain_hotel_options, _fallback_hotel_intent, _has_explicit_hotel_comparison, _has_explicit_stay_scope, _hotel_catalog, _hotel_comparison_base_tier, _hotel_intent_from_decision, _hotel_options, _hotel_proposal_response, _hotel_signature, _hotel_tier, _is_hotel_request, _mentioned_hotel_names, _normalized_hotel_intent, _parse_date, _preference_tier, _previous_proposed_hotel_tier, _resolve_hotel_names, _tiers_in_text, _understand_hotel_intent, _with_stay_scope)
from .intent import (_CHINESE_DAY_NUMBERS, _INCREASE_BY_RE, _REDUCE_BY_RE, _REDUCTION_PHRASE_RE, _cn_number, _increase_target_days, _is_reduction_request, _is_vague_poi_browse_request, _parse_increase_by_days, _parse_reduce_by_days, _reduce_target_days, _requested_day_count)
from .validate import (DecisionJsonError, _clock_minutes, _decision_reply, _default_plan_update_reply, _format_clock, _parse_json_object, _plan_conflict, _reschedule_moved_item, _substantive_plan_signature)
from .document import (_decision_plan_document, _extract_document_plans, _hydrate_decision_plans, _trip_plan_document)
from .plan_edit import (_apply_decision_patches, _apply_plan_update, _dedupe_plans, _deterministic_extend, _deterministic_reduce)
