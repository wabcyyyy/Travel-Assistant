"""整段流式生成：LLM 边流边解析，逐天落地产出（供 Java 整段编排）。

与逐日生成（day_stream）的区别：
- 整段一次 LLM 调用，模型看得见全盘——跨天重复、地理走回头路在生成源头收敛；
- 流式增量解析 daily_plans 数组，每解析出一个完整天立即做事实落地
  （引用背书/高德落坐标）并产出事件，落地耗时与 LLM 生成时间重叠；
- 事件以 JSON Lines 逐行写出（day / day_patch / suggestions / done / error），
  Java 流式读取并逐天落库，前端经既有 SSE 事件逐天点亮。

降级口径：流中断或解析缺天时如实上报已产出天，Java 对缺失天走既有
generate-day 逐日修复链路（含单日反思重试），绝不以占位内容冒充。
"""

import json
import logging
import re
import threading
from collections.abc import Iterator

from app.agent.budget import budget_tier
from app.agent.day_prompts import (
    DAY_ATTRACTION_CONTEXT_LIMIT,
    DAY_FOOD_CONTEXT_LIMIT,
    GENERATION_TEMPERATURE,
    open_trip_prompt,
)
from app.agent.generation_core import (
    PoiSeenRegistry,
    fill_zero_costs,
    norm_poi_key,
    spread_hotels,
    stay_nights,
)
from app.agent.generators import pick_hotels
from app.agent.json_utils import parse_llm_json
from app.agent.landing import filter_plan_items, ground_item
from app.agent.narrative import sanitize_narrative
from app.agent.reference_pool import ReferencePool
from app.agent.suggestions import build_suggestions, fill_suggestion_gaps
from app.agent.trace import record_event
from app.common.config import settings
from app.common.llm_client import StreamCancelled, get_llm_client
from app.schemas.stream_events import (
    DayEvent,
    DayPatchEvent,
    DoneEvent,
    SuggestionsEvent,
    to_wire,
)
from app.schemas.trip import DailyPlan, GenerateDayRequest, Suggestion

logger = logging.getLogger(__name__)

# 流式 max_tokens：整段计划（约 900-1100 tok/天）+ 叙事字段 + 备选池
# （24-40 条，含 60-100 字 intro ≈ 60-80 tok/条）。上限与网关模型输出上限
# （8k）对齐，超长行程（≥6 天）截断风险由缺天修复链路兜底。
_TRIP_STREAM_MAX_TOKENS_CAP = 8192


def _trip_stream_max_tokens(days: int) -> int:
    return max(2800, min(_TRIP_STREAM_MAX_TOKENS_CAP, days * 1500 + 2400))


class DailyPlansStreamParser:
    """从 LLM 流式输出中增量提取 ``daily_plans`` 数组里的完整日计划对象。

    设计：字符级扫描器在累计缓冲上推进（``_pos`` 之前的已消费），
    字符串字面量内的引号/转义/花括号不参与结构判定：
    - SEEK：定位 ``"daily_plans"`` 键（后随 ``:``，字符串值内的同形
      子串因闭合定界符不符而不会误命中），再等 ``[`` 进入数组；
    - ARRAY：跟踪花括号深度（相对元素起点），深度归零即切出元素
      子串并 ``json.loads`` 成功后产出；
    - 截断（流中断）：已完整闭合的天照常产出，``complete=False``。
    """

    _KEY_PATTERN = '"daily_plans"'
    _STATE_SEEK = 0
    _STATE_AFTER_KEY = 1
    _STATE_ARRAY = 2
    _STATE_DONE = 3

    def __init__(self) -> None:
        self._text = ""
        self._pos = 0
        self._state = self._STATE_SEEK
        self._key_idx = 0
        self._in_string = False
        self._escape = False
        self._depth = 0
        self._elem_start = -1
        self.days: list[dict] = []
        self.parse_failures = 0

    def feed(self, delta: str) -> list[dict]:
        """喂入一段增量，返回本次新解析完成的 day 对象列表。"""
        self._text += delta
        out: list[dict] = []
        text = self._text
        n = len(text)
        i = self._pos
        while i < n:
            ch = text[i]
            if self._state == self._STATE_SEEK:
                if ch == self._KEY_PATTERN[self._key_idx]:
                    self._key_idx += 1
                    if self._key_idx == len(self._KEY_PATTERN):
                        self._key_idx = 0
                        self._state = self._STATE_AFTER_KEY
                else:
                    # 失配回退：从下一个字符重新找键起始（简化处理，键唯一且靠前）
                    self._key_idx = 1 if ch == self._KEY_PATTERN[0] else 0
                i += 1
            elif self._state == self._STATE_AFTER_KEY:
                if ch == ":":
                    self._state = self._STATE_ARRAY
                    self._in_string = False
                    self._escape = False
                    self._depth = 0
                    self._elem_start = -1
                elif ch == self._KEY_PATTERN[0]:
                    # 异常字符（如键后又出现同形串）：重置回 SEEK 重找
                    self._state = self._STATE_SEEK
                    self._key_idx = 1
                i += 1
            elif self._state == self._STATE_ARRAY:
                if self._in_string:
                    if self._escape:
                        self._escape = False
                    elif ch == "\\":
                        self._escape = True
                    elif ch == '"':
                        self._in_string = False
                elif ch == '"':
                    self._in_string = True
                elif ch == "{":
                    if self._depth == 0:
                        self._elem_start = i
                    self._depth += 1
                elif ch == "}":
                    self._depth -= 1
                    if self._depth <= 0:
                        self._depth = 0
                        elem = text[self._elem_start : i + 1]
                        try:
                            day = json.loads(elem)
                        except (json.JSONDecodeError, ValueError):
                            self.parse_failures += 1
                        else:
                            if isinstance(day, dict):
                                self.days.append(day)
                                out.append(day)
                elif ch == "]" and self._depth == 0:
                    self._state = self._STATE_DONE
                i += 1
            else:  # DONE
                break
        self._pos = i
        return out

    def finish(self) -> dict:
        """流结束后做整体收割：complete 标志、trip_theme、suggestions。

        complete 必须以完整文本成功解析为准——数组闭合但整体 JSON
        损坏（如畸形括号）时如实判截断，避免 Java 误判缺天范围。
        """
        complete = False
        trip_theme = None
        suggestions: list[dict] = []
        try:
            data = parse_llm_json(self._text)
        except Exception:
            data = None
        if isinstance(data, dict) and isinstance(data.get("daily_plans"), list):
            complete = True
            raw_theme = data.get("trip_theme")
            trip_theme = raw_theme.strip() if isinstance(raw_theme, str) else None
            raw_suggestions = data.get("suggestions")
            if isinstance(raw_suggestions, list):
                suggestions = [s for s in raw_suggestions if isinstance(s, dict)]
        return {
            "complete": complete,
            "trip_theme": trip_theme,
            "suggestions": suggestions,
        }


def _city_label_match(raw_city: str, dest_city: str) -> bool:
    """suggestions 城市归属校验：归一化全等或互为包含（兼容中英注记）。

    "巴塞罗那（Barcelona）" 这类双语注记：除整体外，把括号内的外文名
    单独成词参与比对，避免括号剥离后拉丁名丢失导致误杀。
    """
    b = norm_poi_key(dest_city)
    if not b:
        return False
    text = str(raw_city or "")
    tokens = [text, *re.findall(r"[（(【\[〔]([^）)】\]〕]*)[）)】\]〕]", text)]
    for token in tokens:
        a = norm_poi_key(token)
        if a and (a == b or a in b or b in a):
            return True
    return False


def _filter_suggestions_by_city(raw: list[dict], city: str) -> list[dict]:
    """丢弃模型自报城市与目的地不符的建议（如把示例城市的店铺照抄进来）。"""
    kept: list[dict] = []
    dropped = 0
    for s in raw:
        c = str(s.get("city") or s.get("poiCity") or "").strip()
        if c and not _city_label_match(c, city):
            dropped += 1
            record_event(
                "decision",
                "suggestion_city_mismatch_dropped",
                metadata={"city": c, "poi_name": str(s.get("poi_name") or "")},
            )
            continue
        kept.append(s)
    if dropped:
        record_event(
            "decision", "suggestion_city_filter", metadata={"dest": city, "dropped": dropped, "kept": len(kept)}
        )
    return kept


def _prepare_day(
    raw_day: dict,
    *,
    day_no: int,
    req: GenerateDayRequest,
    ref_pool: ReferencePool,
    seen: PoiSeenRegistry,
    ground_cache: dict,
    price_lookup: dict[str, dict],
) -> dict:
    """单天落地：叙事清洗 → 脏项过滤 → 事实落地 → 同日/跨天双通道去重 → 权威价补水。

    去重顺序：先按归一化名称做廉价判重（重复项不做网络落地），再对落地后
    拿到坐标的点位做同类型近距离（<80m）判重——名称变体
    （"圣家堂" vs "圣家堂大教堂"）由坐标通道兜底。酒店不参与判重
    （全程同一家是摊铺语义），漏排的晚次由 spread_hotels 补齐。
    """
    plan = sanitize_narrative(raw_day)
    plan["day_no"] = day_no
    plan.setdefault("items", [])
    plan["items"] = filter_plan_items(plan["items"])
    kept_items: list[dict] = []
    for item in plan["items"]:
        name = str(item.get("poi_name") or "").strip()
        item_type = str(item.get("item_type") or "")
        if name and seen.is_duplicate(name, item_type):
            record_event("decision", "stream_duplicate_dropped", metadata={"day_no": day_no, "poi_name": name})
            continue
        ground_item(item, city=req.city, ref_pool=ref_pool, ground_cache=ground_cache)
        if name and seen.is_duplicate(name, item_type, item.get("latitude"), item.get("longitude")):
            # 落地后坐标通道判重命中（名称变体指向同一地点）
            record_event(
                "decision", "stream_duplicate_dropped", metadata={"day_no": day_no, "poi_name": name, "via": "coord"}
            )
            continue
        if name:
            seen.register(name, item_type, item.get("latitude"), item.get("longitude"))
        kept_items.append(item)
    plan["items"] = kept_items
    # 0 价补水：餐饮/酒店 cost=0 用权威价覆盖（唯一实现在 generation_core，G-1.3 ③）
    fill_zero_costs([plan], price_lookup)
    return plan


def _plan_model(plan: dict) -> DailyPlan:
    """plan dict → 契约模型（与 generate-day 相同的字段定义，非法字段在此被拒/裁剪）。"""
    return DailyPlan(**plan)


def _suggestion_models(rows: list[dict]) -> list[Suggestion]:
    return [Suggestion(**row) for row in rows if isinstance(row, dict)]


def _raise_if_cancelled(cancel: threading.Event | None) -> None:
    """取消检查点：在 delta 循环与重活（落地/摊铺/备选池）边界调用。"""
    if cancel is not None and cancel.is_set():
        raise StreamCancelled("客户端断开，生成已取消")


def run_generate_trip_stream(req: GenerateDayRequest, cancel: threading.Event | None = None) -> Iterator[dict]:
    """整段流式生成主链路。逐个 yield 事件 dict（见模块 docstring）。

    cancel：客户端断开的取消信号。置位后不再发起新的 LLM 调用，在途流式
    请求由 llm_client 的行级检查掐断；取消不产出 done/suggestions（消费端
    已断开），并以 run_status=cancelled 收尾（metrics 单列 cancelled_runs，
    不误报失败）。
    """
    if cancel is not None and cancel.is_set():
        record_event(
            "decision",
            "run_status",
            status="cancelled",
            metadata={"status": "cancelled", "reason": "cancelled_before_start"},
        )
        return
    if not settings.llm_api_key:
        raise ValueError("未配置 LLM，无法生成行程内容")
    client = get_llm_client()
    total_days = max(int(req.days or 1), 1)
    system, user = open_trip_prompt(req)
    ref_pool = ReferencePool(req.context)
    context = req.context or {}
    candidates = context.get("candidates") or []
    foods = context.get("foods") or []
    hotels = context.get("hotels") or []
    price_lookup: dict[str, dict] = {}
    for poi in list(candidates) + list(foods) + list(hotels):
        name = str(poi.get("name") or "").strip()
        if name:
            price_lookup[name] = poi

    seen: PoiSeenRegistry = PoiSeenRegistry()
    ground_cache: dict = {}
    plans: list[dict] = []
    emitted_nos: list[int] = []
    per_day_suggestions: list[dict] = []
    trip_theme: str | None = None
    stream_error: str | None = None
    parse_failures = 0

    parser = DailyPlansStreamParser()
    cancelled = False
    try:
        deltas = client.stream_chat_deltas(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=GENERATION_TEMPERATURE,
            max_tokens=_trip_stream_max_tokens(total_days),
            model=settings.llm_fast_model or None,
            json_mode=True,
            enable_search=settings.llm_generation_web_search,
            cancel=cancel,
        )
        for delta in deltas:
            _raise_if_cancelled(cancel)
            for raw_day in parser.feed(delta):
                parse_failures = parser.parse_failures
                if len(emitted_nos) >= total_days:
                    # 模型输出超出天数：丢弃并遥测（与 llm_open_trip [:days] 口径一致）
                    record_event("decision", "stream_extra_day_dropped", metadata={"day_no": raw_day.get("day_no")})
                    continue
                # day_no 修正：非法/越界/重复时顺位补齐
                try:
                    day_no = int(raw_day.get("day_no") or 0)
                except (TypeError, ValueError):
                    day_no = 0
                if day_no < 1 or day_no > total_days or day_no in emitted_nos:
                    day_no = next((n for n in range(1, total_days + 1) if n not in emitted_nos), 0)
                if day_no == 0:
                    continue
                # 开放模式也可能按天携带 suggestions（open_day 契约）：收集进备选池
                raw_sugg = raw_day.get("suggestions")
                if isinstance(raw_sugg, list):
                    per_day_suggestions.extend(s for s in raw_sugg if isinstance(s, dict))
                plan = _prepare_day(
                    raw_day,
                    day_no=day_no,
                    req=req,
                    ref_pool=ref_pool,
                    seen=seen,
                    ground_cache=ground_cache,
                    price_lookup=price_lookup,
                )
                plans.append(plan)
                emitted_nos.append(day_no)
                if day_no == 1 and isinstance(plan.get("trip_theme"), str) and plan["trip_theme"].strip():
                    trip_theme = plan["trip_theme"].strip()
                yield to_wire(DayEvent(type="day", plan=_plan_model(plan)))
    except StreamCancelled:
        cancelled = True
        logger.info("trip stream cancelled for %s after %d day(s)", req.city, len(emitted_nos))
    except Exception as exc:
        stream_error = str(exc)
        logger.warning("trip stream interrupted for %s after %d days: %s", req.city, len(emitted_nos), exc)

    if cancelled or (cancel is not None and cancel.is_set()):
        # 取消：消费端已断开，不产出 done/suggestions，也跳过摊铺与备选池等重活；
        # run_status=cancelled 让 metrics 把本次 run 记入 cancelled_runs 而非失败。
        record_event(
            "decision",
            "run_status",
            status="cancelled",
            metadata={"status": "cancelled", "days_emitted": emitted_nos, "days_expected": total_days},
        )
        return

    parse_failures = parser.parse_failures
    final = parser.finish()
    if not trip_theme:
        trip_theme = final.get("trip_theme")

    # 酒店摊铺（LLM 漏排某晚入住时的确定性补齐）：只对新增酒店的天发 patch
    nights = stay_nights(total_days)
    if nights > 0 and req.needs_hotel:
        sizes_before = {id(p): len(p.get("items") or []) for p in plans}
        added = spread_hotels(plans, nights)
        if added:
            for plan in plans:
                if len(plan.get("items") or []) != sizes_before.get(id(plan)):
                    yield to_wire(DayPatchEvent(type="day_patch", plan=_plan_model(plan)))

    # 备选池：模型建议（含按天携带）+ 权威候选补齐 + 联网补齐
    raw_suggestions = final.get("suggestions") or per_day_suggestions
    if per_day_suggestions and final.get("suggestions"):
        raw_suggestions = final["suggestions"] + per_day_suggestions
    raw_suggestions = _filter_suggestions_by_city(raw_suggestions, req.city)
    tier_label, _g, _ppd = budget_tier(req.budget, req.persons or 1, total_days)
    suggestion_rows = build_suggestions(
        plans,
        candidates[:DAY_ATTRACTION_CONTEXT_LIMIT],
        foods[:DAY_FOOD_CONTEXT_LIMIT],
        pick_hotels(hotels, req.hotel_tier, 3),
        raw_suggestions,
        allow_external=True,
    )
    suggestion_rows = fill_suggestion_gaps(suggestion_rows, req.city, budget_tier=tier_label or None)
    yield to_wire(SuggestionsEvent(type="suggestions", items=_suggestion_models(suggestion_rows)))

    record_event(
        "decision",
        "trip_stream_done",
        metadata={
            "city": req.city,
            "days_expected": total_days,
            "days_emitted": emitted_nos,
            "complete": final.get("complete"),
            "parse_failures": parse_failures,
            "stream_error": stream_error,
            "raw_suggestions": len(raw_suggestions),
            "suggestions_final": len(suggestion_rows),
        },
    )
    yield to_wire(
        DoneEvent(
            type="done",
            days_expected=total_days,
            days_emitted=emitted_nos,
            trip_theme=trip_theme,
            complete=bool(final.get("complete")) and stream_error is None,
            message=stream_error,
        )
    )
