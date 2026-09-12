"""旅行规划 Agent 的 HTTP 入口层。

职责：
- 定义 FastAPI 路由，把前端请求转换为对 app.agent 各子模块的函数调用；
- 统一用 ApiResponse 包裹返回结果，并对生成类接口做内部 token 鉴权；
- 把 Pydantic 模型与 agent 层返回值做适配（如 chat-turn、edit-ops 的字段清洗）。

实现要点：
- 写库/生成类接口（generate、adjust、clarify、chat-turn 等）通过 require_internal_token
  依赖校验 X-Agent-Token，未配置时放行；
- edit-ops 返回原始 snake_case 字典，避免 WireModel 的 camel 别名影响跨语言消费方；
- 业务编排逻辑一律下沉到 app.agent.*，本文件只做协议适配与鉴权。

依赖：
- app.agent：各业务子模块；app.schemas：请求/响应模型；app.common.config：鉴权配置。
"""

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse

import logging
import time

from pydantic import ValidationError

from app.agent.butler import run_butler_note, run_poi_intros
from app.agent.chat_draft import run_chat_turn
from app.agent.city_guide import run_city_guide
from app.agent.clarify import run_clarify
from app.agent.day_stream import run_generate_day, run_plan_context
from app.agent.nl_edit import run_edit_ops
from app.agent.workflow import run_adjust, run_generate
from app.agent.local_replan import run_local_replan
from app.agent.tools import find_nearby_pois
from app.agent.tool_registry import registry
from app.agent.usage_store import usage_store
from app.schemas.common import ApiResponse
from app.schemas.agent_ops import (ButlerNoteRequest, ButlerNoteResponse, CityGuideRequest,
                                   CityGuideResponse, PoiIntrosRequest, PoiIntrosResponse,
                                   PoiNearbyItem, PoiNearbyRequest, PoiNearbyResponse)
from app.schemas.trip import (AdjustRequest, AdjustResponse, ChatTurnRequest, ChatTurnResponse,
                              ClarifyRequest, ClarifyResponse, DailyPlan, EditOp, EditOpRequest,
                              GenerateDayRequest, GenerateRequest, GenerateResponse,
                              PlanContextRequest, LocalReplanRequest)
from app.common.config import settings
from app.agent.observability import metrics, observe_run, scene

router = APIRouter()

logger = logging.getLogger(__name__)


def _fail_payload(exc: Exception, endpoint: str) -> ApiResponse[None]:
    """把异常转成对外安全的错误信封。

    非 ValueError（AttributeError/KeyError/pydantic ValidationError 等）的原文
    可能包含字段校验细节、SQL 片段或第三方报错，直接透传等于泄露内部实现；
    这里完整记日志，对外只给通用文案。ValueError 是业务层有意抛出的可读降级
    原因（如"开放研究失败"），保留但裁剪长度。
    """
    logger.exception("[%s] request failed: %s", endpoint, exc)
    # ValidationError 是 ValueError 子类，但其原文含字段级校验细节，不外泄。
    if isinstance(exc, ValidationError):
        return ApiResponse.fail("请求参数不合法", code=400)
    if isinstance(exc, ValueError):
        return ApiResponse.fail(str(exc)[:200], code=500)
    return ApiResponse.fail("服务暂时不可用，请稍后重试", code=500)


def require_internal_token(x_agent_token: str | None = Header(default=None)) -> None:
    """Protect expensive mutation/generation endpoints when an internal token is configured."""
    expected = settings.agent_internal_token
    if expected and x_agent_token != expected:
        raise HTTPException(status_code=401, detail="invalid agent token")


@router.get("/hello")
def hello() -> ApiResponse[str]:
    return ApiResponse.ok("hello from travel-agent-python")


@router.get("/health")
def health() -> ApiResponse[dict]:
    return ApiResponse.ok({"status": "up"})


@router.get("/v1/metrics")
def agent_metrics(_auth: None = Depends(require_internal_token)) -> ApiResponse[dict]:
    """返回进程内聚合指标；生产环境应替换为 Prometheus/OTel exporter。"""
    return ApiResponse.ok(metrics.snapshot())


_RANGE_SECONDS = {"1h": 3600, "24h": 86400, "7d": 7 * 86400, "30d": 30 * 86400}


def _usage_bucket(range_key: str) -> int:
    """分桶粒度：1h 按分钟、24h 按小时、7d/30d 按天。"""
    if range_key == "1h":
        return 60
    if range_key == "24h":
        return 3600
    return 86400


@router.get("/v1/usage")
def agent_usage(range: str = "24h", limit: int = 200, offset: int = 0,
                _auth: None = Depends(require_internal_token)) -> ApiResponse[dict]:
    """SQLite 落库的 LLM 用量历史（汇总/场景/模型/趋势/明细），重启不清零。"""
    range_key = range if range in _RANGE_SECONDS else "24h"
    end = int(time.time()) + 60
    start = end - _RANGE_SECONDS[range_key]
    bucket = _usage_bucket(range_key)
    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))
    return ApiResponse.ok({
        "range": range_key,
        "bucket": bucket,
        "summary": usage_store.summary(start, end),
        "by_scene": usage_store.by_scene(start, end),
        "by_model": usage_store.by_model(start, end),
        "timeline": usage_store.timeline(start, end, bucket),
        "calls": usage_store.calls(start, end, limit, offset),
    })


@router.get("/v1/metrics/prometheus", response_class=PlainTextResponse)
def agent_metrics_prometheus(_auth: None = Depends(require_internal_token)) -> PlainTextResponse:
    return PlainTextResponse(metrics.prometheus_text(), media_type="text/plain; version=0.0.4")


@router.get("/v1/tools")
def agent_tools(_auth: None = Depends(require_internal_token)) -> ApiResponse[list[dict]]:
    """返回已注册工具的脱敏治理元数据，不返回可执行 handler。"""
    return ApiResponse.ok(registry.public_specs())


@router.get("/v1/runs/{run_id}")
def agent_run_trace(run_id: str,
                    _auth: None = Depends(require_internal_token)) -> ApiResponse[dict]:
    """查询最近一次运行的脱敏轨迹；轨迹过期后返回 404。"""
    trace = metrics.get_trace(run_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="agent run not found or expired")
    return ApiResponse.ok(trace)


@router.get("/test-generate")
@scene("generate")
def test_generate(_auth: None = Depends(require_internal_token)) -> ApiResponse[dict]:
    """开发联通性样例；配置内部 token 后不允许匿名访问。"""
    return ApiResponse.ok(
        {
            "city": "北京",
            "days": 2,
            "daily_plans": [
                {
                    "day_no": 1,
                    "items": [
                        {
                            "item_type": "attraction",
                            "poi_name": "故宫博物院",
                            "start_time": "09:00",
                            "duration_min": 180,
                            "cost": 60.0,
                        },
                        {
                            "item_type": "attraction",
                            "poi_name": "景山公园",
                            "start_time": "14:00",
                            "duration_min": 60,
                            "cost": 2.0,
                        },
                    ],
                },
                {
                    "day_no": 2,
                    "items": [
                        {
                            "item_type": "attraction",
                            "poi_name": "八达岭长城",
                            "start_time": "08:30",
                            "duration_min": 240,
                            "cost": 40.0,
                        }
                    ],
                },
            ],
            "budget_estimate": {"门票": 102.0, "餐饮": 180.0, "交通": 100.0, "酒店": 500.0},
        }
    )


@router.post("/v1/generate")
@scene("generate")
def generate(req: GenerateRequest,
             x_request_id: str | None = Header(default=None),
             _auth: None = Depends(require_internal_token)) -> ApiResponse[GenerateResponse]:
    trace = None
    try:
        with observe_run(request_id=x_request_id) as trace:
            result = run_generate(req)
        payload = ApiResponse.ok(result)
        return JSONResponse(
            content=payload.model_dump(mode="json", by_alias=True),
            headers={"X-Agent-Run-ID": trace.run_id, "X-Request-ID": trace.request_id},
        )
    except Exception as e:  # noqa: BLE001 - 统一转安全错误信封
        payload = _fail_payload(e, "generate")
        headers = ({"X-Agent-Run-ID": trace.run_id, "X-Request-ID": trace.request_id}
                   if trace is not None else None)
        return JSONResponse(content=payload.model_dump(mode="json", by_alias=True), headers=headers)


@router.post("/v1/adjust")
@scene("chat")
def adjust(req: AdjustRequest, _auth: None = Depends(require_internal_token)) -> ApiResponse[AdjustResponse]:
    return ApiResponse.ok(run_adjust(req))


@router.post("/v1/clarify")
@scene("clarify")
def clarify(req: ClarifyRequest, _auth: None = Depends(require_internal_token)) -> ApiResponse[ClarifyResponse]:
    try:
        return ApiResponse.ok(run_clarify(req))
    except ValueError as e:
        return ApiResponse.fail(str(e))


@router.post("/v1/edit-ops")
@scene("chat")
def edit_ops(req: EditOpRequest, _auth: None = Depends(require_internal_token)) -> ApiResponse[list[dict]]:
    try:
        ops = run_edit_ops(req)
        # 输出 snake_case 原始键，避免 WireModel 的 camel 别名影响跨语言消费方
        return ApiResponse.ok([op.model_dump() for op in ops])
    except ValueError as e:
        return ApiResponse.fail(str(e))


@router.post("/v1/plan-context")
@scene("assist")
def plan_context(req: PlanContextRequest, _auth: None = Depends(require_internal_token)) -> ApiResponse[dict]:
    # itinerary_id 透传给研究链路发布进度事件；旧调用方不传则不发布
    return ApiResponse.ok(run_plan_context(req.city, req.preferences,
                                           itinerary_id=req.itinerary_id))


@router.post("/v1/generate-day")
@scene("generate")
def generate_day(req: GenerateDayRequest,
                 x_request_id: str | None = Header(default=None),
                 _auth: None = Depends(require_internal_token)) -> ApiResponse[DailyPlan]:
    trace = None
    try:
        with observe_run(request_id=req.request_id or x_request_id, action_id=req.action_id) as trace:
            result = run_generate_day(req)
        payload = ApiResponse.ok(result)
        return JSONResponse(
            content=payload.model_dump(mode="json", by_alias=True),
            headers={"X-Agent-Run-ID": trace.run_id, "X-Request-ID": trace.request_id},
        )
    except Exception as e:  # noqa: BLE001 - 统一转安全错误信封
        payload = _fail_payload(e, "generate-day")
        headers = ({"X-Agent-Run-ID": trace.run_id, "X-Request-ID": trace.request_id}
                   if trace is not None else None)
        return JSONResponse(content=payload.model_dump(mode="json", by_alias=True), headers=headers)


@router.post("/v1/replan-local")
@scene("generate")
def replan_local(req: LocalReplanRequest,
                 x_request_id: str | None = Header(default=None),
                 _auth: None = Depends(require_internal_token)) -> ApiResponse[dict]:
    trace = None
    try:
        with observe_run(request_id=req.request_id or x_request_id, action_id=req.action_id) as trace:
            result = run_local_replan(req)
        payload = ApiResponse.ok(result)
        return JSONResponse(content=payload.model_dump(mode="json", by_alias=True),
                            headers={"X-Agent-Run-ID": trace.run_id, "X-Request-ID": trace.request_id})
    except Exception as exc:  # noqa: BLE001 - 统一转安全错误信封
        payload = _fail_payload(exc, "replan-local")
        headers = ({"X-Agent-Run-ID": trace.run_id, "X-Request-ID": trace.request_id}
                   if trace is not None else None)
        return JSONResponse(content=payload.model_dump(mode="json", by_alias=True), headers=headers)


@router.post("/v1/chat-turn")
@scene("chat")
def chat_turn(req: ChatTurnRequest,
              _auth: None = Depends(require_internal_token)) -> ApiResponse[ChatTurnResponse]:
    try:
        return ApiResponse.ok(run_chat_turn(req))
    except ValueError as e:
        return ApiResponse.fail(str(e))


@router.post("/v1/butler-note")
@scene("assist")
def butler_note(req: ButlerNoteRequest,
                _auth: None = Depends(require_internal_token)) -> ApiResponse[ButlerNoteResponse]:
    try:
        # model_dump() 输出 snake_case 键，与 run_butler_note 读取的键一致
        return ApiResponse.ok(ButlerNoteResponse(note=run_butler_note(req.model_dump())))
    except Exception as exc:
        logger.warning("butler_note failed: %s", exc)
        return ApiResponse.ok(ButlerNoteResponse(note=""))


@router.post("/v1/poi-intros")
@scene("assist")
def poi_intros(req: PoiIntrosRequest,
               _auth: None = Depends(require_internal_token)) -> ApiResponse[PoiIntrosResponse]:
    try:
        # Pydantic 已保证 list[str]；沿用历史行为过滤空名
        names = [n for n in req.names if n]
        # M3-②：intent 透传进介绍 Prompt（为空时由 butler 层降级为口碑/地理理由）
        return ApiResponse.ok(PoiIntrosResponse(
            intros=run_poi_intros(req.city, names, intent=req.intent)))
    except Exception:
        return ApiResponse.ok(PoiIntrosResponse())


@router.post("/v1/poi-nearby")
@scene("assist")
def poi_nearby(req: PoiNearbyRequest,
               _auth: None = Depends(require_internal_token)) -> ApiResponse[PoiNearbyResponse]:
    """同城权威 POI 近邻（轻量 GraphRAG）：名称解析坐标或直接传坐标。

    坐标缺失时返回空列表——附近推荐只使用权威库真实坐标，不伪造。
    参数换算保持与改造前逐项一致：0 值 falsy 归默认/None；坐标经
    Pydantic lax 转换后原样透传（0.0 仍传 0.0，由底层判无效坐标）。
    """
    try:
        rows = find_nearby_pois(
            req.city,
            name=(req.name or None),
            latitude=req.latitude,
            longitude=req.longitude,
            limit=(req.limit or 5),
            radius_m=(req.radius_m or None),
            category=(req.category or None),
        )
        return ApiResponse.ok(PoiNearbyResponse(items=[PoiNearbyItem.model_validate(r) for r in rows]))
    except Exception:
        return ApiResponse.ok(PoiNearbyResponse())


@router.post("/v1/city-guide")
@scene("assist")
def city_guide(req: CityGuideRequest,
               _auth: None = Depends(require_internal_token)) -> ApiResponse[CityGuideResponse]:
    try:
        # by_alias=True：user_input 字段 dump 成 wire 键 "input"，与 run_city_guide 读取的键一致
        data = run_city_guide(req.model_dump(by_alias=True))
        return ApiResponse.ok(CityGuideResponse.model_validate(data))
    except Exception:
        return ApiResponse.fail("城市引导服务暂不可用")
