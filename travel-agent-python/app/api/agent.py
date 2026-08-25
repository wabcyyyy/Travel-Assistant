from fastapi import APIRouter, Depends, Header, HTTPException

from app.agent.butler import run_butler_note, run_poi_intros
from app.agent.chat_draft import run_chat_turn
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


@router.get("/test-generate")
def test_generate() -> ApiResponse[dict]:
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
def generate(req: GenerateRequest, _auth: None = Depends(require_internal_token)) -> ApiResponse[GenerateResponse]:
    try:
        return ApiResponse.ok(run_generate(req))
    except ValueError as e:
        return ApiResponse.fail(str(e))


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
def generate_day(req: GenerateDayRequest, _auth: None = Depends(require_internal_token)) -> ApiResponse[DailyPlan]:
    try:
        return ApiResponse.ok(run_generate_day(req))
    except ValueError as e:
        return ApiResponse.fail(str(e))


@router.post("/v1/chat-turn")
def chat_turn(req: ChatTurnRequest) -> ApiResponse[ChatTurnResponse]:
    try:
        return ApiResponse.ok(run_chat_turn(req))
    except ValueError as e:
        return ApiResponse.fail(str(e))


@router.post("/v1/butler-note")
def butler_note(req: dict) -> ApiResponse[dict]:
    try:
        return ApiResponse.ok({"note": run_butler_note(req)})
    except Exception:
        return ApiResponse.ok({"note": ""})


@router.post("/v1/poi-intros")
def poi_intros(req: dict) -> ApiResponse[dict]:
    try:
        names = [n for n in (req.get("names") or []) if isinstance(n, str) and n]
        return ApiResponse.ok({"intros": run_poi_intros(req.get("city", ""), names)})
    except Exception:
        return ApiResponse.ok({"intros": {}})
