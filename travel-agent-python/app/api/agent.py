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
from fastapi.responses import JSONResponse

from app.agent.butler import run_butler_note, run_poi_intros
from app.agent.chat_draft import run_chat_turn
from app.agent.city_guide import run_city_guide
from app.agent.clarify import run_clarify
from app.agent.day_stream import run_generate_day, run_plan_context
from app.agent.nl_edit import run_edit_ops
from app.agent.workflow import run_adjust, run_generate
from app.schemas.common import ApiResponse
from app.schemas.trip import (AdjustRequest, AdjustResponse, ChatTurnRequest, ChatTurnResponse,
                              ClarifyRequest, ClarifyResponse, DailyPlan, EditOp, EditOpRequest,
                              GenerateDayRequest, GenerateRequest, GenerateResponse,
                              PlanContextRequest)
from app.common.config import settings
from app.agent.observability import metrics, observe_run

router = APIRouter()


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


@router.get("/v1/runs/{run_id}")
def agent_run_trace(run_id: str,
                    _auth: None = Depends(require_internal_token)) -> ApiResponse[dict]:
    """查询最近一次运行的脱敏轨迹；轨迹过期后返回 404。"""
    trace = metrics.get_trace(run_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="agent run not found or expired")
    return ApiResponse.ok(trace)


@router.get("/test-generate")
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
def generate(req: GenerateRequest,
             _auth: None = Depends(require_internal_token)) -> ApiResponse[GenerateResponse]:
    trace = None
    try:
        with observe_run() as trace:
            result = run_generate(req)
        payload = ApiResponse.ok(result)
        return JSONResponse(
            content=payload.model_dump(mode="json", by_alias=True),
            headers={"X-Agent-Run-ID": trace.run_id},
        )
    except ValueError as e:
        payload = ApiResponse.fail(str(e))
        headers = {"X-Agent-Run-ID": trace.run_id} if trace is not None else None
        return JSONResponse(content=payload.model_dump(mode="json", by_alias=True), headers=headers)


@router.post("/v1/adjust")
def adjust(req: AdjustRequest, _auth: None = Depends(require_internal_token)) -> ApiResponse[AdjustResponse]:
    return ApiResponse.ok(run_adjust(req))


@router.post("/v1/clarify")
def clarify(req: ClarifyRequest, _auth: None = Depends(require_internal_token)) -> ApiResponse[ClarifyResponse]:
    try:
        return ApiResponse.ok(run_clarify(req))
    except ValueError as e:
        return ApiResponse.fail(str(e))


@router.post("/v1/edit-ops")
def edit_ops(req: EditOpRequest, _auth: None = Depends(require_internal_token)) -> ApiResponse[list[dict]]:
    try:
        ops = run_edit_ops(req)
        # 输出 snake_case 原始键，避免 WireModel 的 camel 别名影响跨语言消费方
        return ApiResponse.ok([op.model_dump() for op in ops])
    except ValueError as e:
        return ApiResponse.fail(str(e))


@router.post("/v1/plan-context")
def plan_context(req: PlanContextRequest, _auth: None = Depends(require_internal_token)) -> ApiResponse[dict]:
    return ApiResponse.ok(run_plan_context(req.city, req.preferences))


@router.post("/v1/generate-day")
def generate_day(req: GenerateDayRequest,
                 _auth: None = Depends(require_internal_token)) -> ApiResponse[DailyPlan]:
    trace = None
    try:
        with observe_run() as trace:
            result = run_generate_day(req)
        payload = ApiResponse.ok(result)
        return JSONResponse(
            content=payload.model_dump(mode="json", by_alias=True),
            headers={"X-Agent-Run-ID": trace.run_id},
        )
    except ValueError as e:
        payload = ApiResponse.fail(str(e))
        headers = {"X-Agent-Run-ID": trace.run_id} if trace is not None else None
        return JSONResponse(content=payload.model_dump(mode="json", by_alias=True), headers=headers)


@router.post("/v1/chat-turn")
def chat_turn(req: ChatTurnRequest,
              _auth: None = Depends(require_internal_token)) -> ApiResponse[ChatTurnResponse]:
    try:
        return ApiResponse.ok(run_chat_turn(req))
    except ValueError as e:
        return ApiResponse.fail(str(e))


@router.post("/v1/butler-note")
def butler_note(req: dict, _auth: None = Depends(require_internal_token)) -> ApiResponse[dict]:
    try:
        return ApiResponse.ok({"note": run_butler_note(req)})
    except Exception:
        return ApiResponse.ok({"note": ""})


@router.post("/v1/poi-intros")
def poi_intros(req: dict, _auth: None = Depends(require_internal_token)) -> ApiResponse[dict]:
    try:
        names = [n for n in (req.get("names") or []) if isinstance(n, str) and n]
        return ApiResponse.ok({"intros": run_poi_intros(req.get("city", ""), names)})
    except Exception:
        return ApiResponse.ok({"intros": {}})

@router.post("/v1/city-guide")
def city_guide(req: dict, _auth: None = Depends(require_internal_token)) -> ApiResponse[dict]:
    try:
        return ApiResponse.ok(run_city_guide(req))
    except Exception:
        return ApiResponse.fail("城市引导服务暂不可用")
