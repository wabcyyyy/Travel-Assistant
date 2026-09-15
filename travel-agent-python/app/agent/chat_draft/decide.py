"""对话改行程的编排层（orchestrator）与唯一对外入口 run_chat_turn。

职责：
- _decide_plan_change：把当前计划+用户要求发给 LLM，要求返回封闭动作集之一的 JSON
  （hotel_proposal / plan_update / rewrite_plan / clarify / no_change）；
- run_chat_turn：按 mode 分流——酒店走候选确认，行程走 plan_edit 落地，
  并对结果跑时间冲突/实质变更/酒店签名等安全校验，最后返回可预览的草稿。

实现要点：
- 封闭动作集（finite action space）：用户千奇百怪的说法都被归约到有限几种能力，
  参数内容（整份 JSON）由 LLM 填充，代码只负责执行与校验；
- 大改（改天数/重排）优先让模型输出完整 plan_document（rewrite_plan），
  小改才用补丁，避免脆弱的“大量 move/delete”表达；
- 模型提案失败时有一次修复重试，仍失败且属精简/延长类再退回确定性兜底；
- 本层只产出草稿，任何落库都由前端“确认应用”触发，绝不直接写数据库。

依赖：intent / validate / document / plan_edit / hotel 全部。
"""

import contextlib
import json
import logging
from datetime import date, timedelta

from app.agent import tools
from app.agent.memory import dialogue_messages
from app.common.config import settings
from app.common.llm_client import get_llm_client
from app.schemas.trip import (
    MAX_TRIP_DAYS,
    ChatTurnRequest,
    ChatTurnResponse,
)

from .document import _decision_plan_document, _trip_plan_document
from .hotel import (
    _fallback_hotel_intent,
    _has_explicit_hotel_comparison,
    _hotel_catalog,
    _hotel_comparison_base_tier,
    _hotel_intent_from_decision,
    _hotel_proposal_response,
    _hotel_signature,
    _is_hotel_request,
    _understand_hotel_intent,
    _with_stay_scope,
)
from .intent import (
    _increase_target_days,
    _is_reduction_request,
    _is_vague_poi_browse_request,
    _reduce_target_days,
    _requested_day_count,
)
from .plan_edit import (
    _apply_plan_update,
    _dedupe_plans,
    _deterministic_extend,
    _deterministic_reduce,
)
from .validate import (
    DecisionJsonError,
    _decision_reply,
    _default_plan_update_reply,
    _parse_json_object,
    _plan_conflict,
    _substantive_plan_signature,
)

logger = logging.getLogger(__name__)


def _decide_plan_change(req: ChatTurnRequest, hotels: list[dict], feedback: str | None = None) -> dict:
    document = _decision_plan_document(req)
    system = (
        "你是旅行计划 JSON 编辑器。你必须先理解用户自然语言，再从下列【封闭动作集】中选择一种，且只输出JSON。"
        "动作集是有限、封闭的能力，无法穷举用户说法，但任何要求都应被归约到其中之一："
        "1) hotel_proposal：凡涉及住宿、酒店、宾馆、房型或某酒店品牌，无论措辞，都必须用它；"
        "绝不直接修改 days 里的 hotel 项目，只填 hotel_request。"
        "2) plan_update：对现有行程“小修小补”——移动单个项目、改时间、删/加个别景点；只返回短补丁 patches。"
        "3) rewrite_plan：对行程做“大改/重生成”，例如改变总天数（减少/增加/改成 N 天）、"
        "或“重新安排/重排/整体优化/重生成”景点。此时严禁用一堆 move/delete 补丁去表达，"
        "而必须直接返回一份完整的 plan_document（结构见下），由确定性代码安全落地。"
        "4) clarify：信息不足、存在冲突或无法安全安排时使用，输出澄清问题。"
        "5) no_change：确实无需修改时使用。"
        "patches的op只能是delete、move、update、add、set_day_note。"
        "delete填item_id；move填item_id、day_no和可选position；"
        "update填item_id及fields，fields只允许start_time/end_time/duration_min/tag/remark；"
        "add填day_no及item且不得新增酒店；set_day_note填day_no和note。酒店项目不得出现在patches中。"
        "rewrite_plan 的 plan_document 必须是与“当前计划JSON”同结构的完整计划："
        '{"schema_version":1,"trip":{"city":"...","days":目标天数,"persons":...,"budget":...,'
        '"start_date":...,"end_date":...,"preferences":...,"hotel_tier":...},'
        '"days":[{"day_no":1,"note":"主题","items":['
        '{"id":现有id,"start_time":"...","remark":"..."} 或 {"item_type":"attraction","poi_name":"新景点"}]}]}。'
        "保持的项目请带原 id（只改允许字段，可改变 day_no 来重排）；要删除的项目直接不写入；"
        "要新增的项目不带 id 且不得是 hotel。trip 中城市/人数/预算等元数据必须与当前一致，只允许 days 变化。"
        "用户明确说减少/增加/改成 N 天时，plan_document.trip.days 必须等于该目标天数；未提天数时保持原天数。"
        "减少不重要或重复景点、或要求行程宽松时，应在 rewrite_plan 里真实删减/重排，不得只改 note。"
        "新增或调整时间时不得与同一天已有项目重叠；若无法安全安排应使用clarify。"
        "reply必须结合本次具体动作写清楚，不得照抄占位词；只改用户要求的部分。"
        "信息不足且无法安全推断时使用clarify。酒店名称必须优先从hotel_catalog中选择完整名称。"
        "day_numbers必须把‘最后一天、返程前一晚’等自然语言换算成具体日序号。"
        "hotel_request.action只能是specific、cheaper、same、better、best；"
        "candidate_mode只能是exact或recommend，明确指定酒店时用exact，否则用recommend。"
        "输出结构："
        '{"mode":"hotel_proposal|plan_update|rewrite_plan|clarify|no_change","reply":"说明本次具体处理结果",'
        '"hotel_request":{"action":"specific","hotel_names":["目录完整名称"],"hotel_query":"用户说法",'
        '"target_tier":"经济型|舒适型|高档型|豪华型|奢华型|null","day_numbers":[4],'
        '"night_count":1,"candidate_mode":"exact|recommend","candidate_count":3},'
        '"target_days":5或null,"patches":[{"op":"delete","item_id":123}],'
        '"plan_document":完整计划或null,'
        '"operations":[{"action":"动作","day_numbers":[1],"summary":"说明"}]}'
    )
    messages = [{"role": "system", "content": system}]
    messages.extend(dialogue_messages(req.history))
    user_content = (
        f"当前计划JSON：{json.dumps(document, ensure_ascii=False)}\n"
        f"hotel_catalog：{json.dumps(_hotel_catalog(hotels), ensure_ascii=False)}\n"
        f"用户本轮要求：{req.message}"
    )
    if feedback:
        user_content += f"\n\n[上一轮校验反馈，必须修正] {feedback}"
    messages.append({"role": "user", "content": user_content})
    client = get_llm_client()
    raw = client.chat(
        messages,
        temperature=0.1,
        max_tokens=1800,
        model=settings.llm_fast_model or None,
        json_mode=True,
    )
    try:
        return _parse_json_object(raw)
    except DecisionJsonError:
        logger.warning("plan decision returned malformed JSON; requesting one repair")
        repaired = client.chat(
            [
                {"role": "system", "content": "修复下面的JSON。保持原意，只输出一个语法正确的JSON对象，不要解释。"},
                {"role": "user", "content": raw[:12000]},
            ],
            temperature=0,
            max_tokens=1800,
            model=settings.llm_fast_model or None,
            json_mode=True,
        )
        return _parse_json_object(repaired)


def run_chat_turn(req: ChatTurnRequest) -> ChatTurnResponse:
    hotels = tools.search_hotels(req.city, limit=30)
    if _is_vague_poi_browse_request(req.message) and not _is_hotel_request(req, hotels):
        return ChatTurnResponse(
            reply=(
                "### 可以为你推荐其他景点\n\n"
                "请告诉我想查看哪一天、偏好的类型（自然 / 人文 / 亲子等），"
                "或直接说出想替换的景点；当前行程没有修改。"
            ),
            plans=[],
            changed=False,
            hotel_options=[],
            requires_confirmation=False,
            plan_document=_trip_plan_document(req),
            operations=[],
        )
    requested_days = _requested_day_count(req.message, req.days)
    if requested_days is not None and requested_days > MAX_TRIP_DAYS:
        return ChatTurnResponse(
            reply=f"### 行程天数上限\n\n每次生成行程最多支持 {MAX_TRIP_DAYS} 天，本次没有修改行程。",
            plans=[],
            changed=False,
            hotel_options=[],
            requires_confirmation=False,
            plan_document=_trip_plan_document(req),
            operations=[],
        )
    try:
        decision = _decide_plan_change(req, hotels)
    except DecisionJsonError as exc:
        logger.warning("unified plan decision remained invalid after repair: %s", exc)
        return ChatTurnResponse(
            reply="### 暂时没能生成可靠草稿\n\n模型返回的计划格式不完整，本次没有修改行程。请直接重试一次。",
            plans=[],
            changed=False,
            plan_document=_trip_plan_document(req),
        )
    except Exception as exc:
        logger.warning("unified plan decision failed: %s", exc)
        # 仅在模型不可用时启用旧规则兜底；正常语义路由不依赖关键词。
        if _is_hotel_request(req, hotels):
            intent = _understand_hotel_intent(req, hotels)
            return _hotel_proposal_response(req, hotels, intent)
        return ChatTurnResponse(
            reply=("### 行程助手暂时不可用\n\n本次没有修改行程，请稍后重试；如果要求较复杂，也可以拆成一步发送。"),
            plans=[],
            changed=False,
            plan_document=_trip_plan_document(req),
        )

    mode = str(decision.get("mode") or "no_change")
    operations = decision.get("operations") if isinstance(decision.get("operations"), list) else []
    # 明确酒店请求必须优先进入候选流程。模型有时会把“我想换个酒店”
    # 误判成普通 plan_update（甚至带空 patches），这时不能返回一句无操作的
    # 普通回复，更不能让普通补丁绕过酒店/房型确认。
    if _is_hotel_request(req, hotels) and mode != "hotel_proposal":
        return _hotel_proposal_response(req, hotels, _understand_hotel_intent(req, hotels), operations)
    if mode == "hotel_proposal":
        intent = _hotel_intent_from_decision(req, hotels, decision)
        if _has_explicit_hotel_comparison(req.message):
            intent = _with_stay_scope(
                _fallback_hotel_intent(req.message, _hotel_comparison_base_tier(req, hotels)), req, hotels
            )
        response = _hotel_proposal_response(req, hotels, intent, operations, str(decision.get("reply") or ""))
        # 模型候选参数不完整时再用确定性意图识别重试一次，避免无卡片无提示。
        if not response.hotel_options and _is_hotel_request(req, hotels):
            return _hotel_proposal_response(req, hotels, _understand_hotel_intent(req, hotels), operations)
        return response

    if mode in ("plan_update", "rewrite_plan"):
        reduction_requested = _is_reduction_request(req.message)
        reduce_target = _reduce_target_days(req)
        extension_requested = _increase_target_days(req) is not None
        increase_target = _increase_target_days(req)
        final_decision = decision
        plans = _apply_plan_update(decision, req)
        if plans is None:
            # 模型提案未通过确定性校验：把校验要点反馈给模型再修一轮，
            # 仍失败且属于精简/去重/缩短类请求时，才退回确定性兜底。这样既不放弃
            # 模型的语义理解能力，又比直接报错更可靠。
            feedback = (
                "你上一轮返回的 plan_update 未通过校验，不要修改。请严格只使用现有行程中真实存在的 item_id"
                "（切勿编造 id）；缩短行程时必须把被移除日期里的全部项目用 delete 删除或 move 到保留日期；"
                "hotel 项目不得出现在 patches 中；也不要改动价格、坐标、城市、人数或预算。"
            )
            try:
                repaired = _decide_plan_change(req, hotels, feedback=feedback)
            except Exception as exc:
                logger.warning("plan_update repair attempt failed: %s", exc)
                repaired = None
            if repaired and str(repaired.get("mode") or "plan_update") in ("plan_update", "rewrite_plan"):
                repaired_plans = _apply_plan_update(repaired, req)
                if repaired_plans is not None:
                    plans = repaired_plans
                    final_decision = repaired
        if plans is None and reduction_requested:
            # 模型编辑失败时，对“精简/去重/缩短行程”这类请求做确定性兜底，
            # 避免直接报“无法生成安全草稿”而完全无法操作。
            plans = _deterministic_reduce(req, target_days=reduce_target)
        if plans is None and extension_requested:
            # 模型编辑失败时，对“加/延长 N 天”这类请求用单日生成器确定性补齐新增日期，
            # 避免直接报“无法生成安全草稿”而完全无法操作。
            target = increase_target or (req.days + 1)
            plans = _deterministic_extend(req, target)
        if plans is None:
            return ChatTurnResponse(
                reply="### 无法生成安全草稿\n\n模型返回的计划结构或行程元数据不合法，本次未修改任何内容。",
                plans=[],
                changed=False,
                plan_document=_trip_plan_document(req),
            )
        # 防御性去重：任何环节的遗漏都在此最后兜底，保证草稿无跨天重复景点。
        plans = _dedupe_plans(plans)
        # 缩短/延长行程会顺带移除或新增日期里的住宿，这是用户明确要求的副作用，允许直接应用；
        # 其余情况下（天数未变却出现酒店差异）则必须走酒店确认流程，防止模型偷偷改住宿。
        if _hotel_signature(plans) != _hotel_signature(req.plans) and len(plans) == req.days:
            return ChatTurnResponse(
                reply="### 需要先确认住宿\n\n检测到酒店发生变化。请选择酒店和房型后再应用，本次没有直接修改行程。",
                plans=[],
                changed=False,
                plan_document=_trip_plan_document(req),
            )
        if _substantive_plan_signature(plans) == _substantive_plan_signature(req.plans):
            return ChatTurnResponse(
                reply=(
                    "### 还没有形成有效调整\n\n"
                    "本次建议没有实际改变景点、顺序或时间，因此未生成可应用草稿。"
                    "请说明希望删减、移动或延长停留的具体安排。"
                ),
                plans=[],
                changed=False,
                plan_document=_trip_plan_document(req),
                operations=operations,
            )
        conflict = _plan_conflict(plans)
        if conflict:
            day_no, first, second = conflict
            return ChatTurnResponse(
                reply=(
                    "### 新安排存在时间冲突\n\n"
                    f"第 **{day_no} 天**的「{first}」与「{second}」时间重叠，"
                    "本次没有生成可应用草稿。请指定要移动或替换其中哪一项。"
                ),
                plans=[],
                changed=False,
                plan_document=_trip_plan_document(req),
                operations=operations,
            )
        updated_document = _trip_plan_document(req)
        updated_document["days"] = plans
        updated_document["trip"]["days"] = len(plans)
        if req.start_date:
            with contextlib.suppress(ValueError):
                updated_document["trip"]["end_date"] = (
                    date.fromisoformat(req.start_date) + timedelta(days=len(plans) - 1)
                ).isoformat()
        return ChatTurnResponse(
            reply=_decision_reply(final_decision.get("reply"), _default_plan_update_reply(req, plans)),
            plans=plans,
            changed=plans != req.plans,
            plan_document=updated_document,
            operations=operations,
        )

    return ChatTurnResponse(
        reply=_decision_reply(decision.get("reply"), "本次没有需要修改的内容。"),
        plans=[],
        changed=False,
        plan_document=_trip_plan_document(req),
        operations=operations,
    )
