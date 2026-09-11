"""受控工具目录。

工具只能通过显式注册后执行，目录同时提供 Function Calling schema、参数校验、
调用预算和脱敏审计事件。写入型工具默认不注册，避免模型或不可信工具结果
绕过 Java 业务服务直接改变行程状态。
"""

from __future__ import annotations

import contextvars
import uuid
from dataclasses import dataclass
from typing import Any, Callable
from concurrent.futures import ThreadPoolExecutor

from app.agent.trace import registry_tool_call, record_event, trace_span
from app.agent.run_limits import current_limits
from app.common.config import settings
from app.schemas.trip import MAX_TRIP_DAYS


class ToolInvocationError(ValueError):
    """工具不存在、参数不合法、未确认或超过预算。"""


@dataclass(frozen=True)
class ToolSpec:
    name: str
    version: str
    description: str
    parameters: dict[str, Any]
    read_only: bool
    risk_level: str
    timeout_seconds: float
    max_calls: int
    retry_policy: dict[str, Any]
    requires_confirmation: bool
    idempotent: bool
    handler: Callable[..., Any]

    def function_schema(self) -> dict[str, Any]:
        return {"type": "function", "function": {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }}


_budget: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "agent_tool_budget", default=None
)


def begin_tool_budget() -> contextvars.Token:
    return _budget.set({"total": 0, "by_tool": {}})


def end_tool_budget(token: contextvars.Token) -> None:
    _budget.reset(token)


def tool_budget_snapshot() -> dict[str, Any]:
    current = _budget.get() or {"total": 0, "by_tool": {}}
    return {"total": int(current.get("total", 0)),
            "by_tool": dict(current.get("by_tool", {}))}


def _type_matches(value: Any, expected: str) -> bool:
    return {
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "array": isinstance(value, list),
        "object": isinstance(value, dict),
    }.get(expected, True)


def _validate_parameters(spec: ToolSpec, params: dict[str, Any]) -> None:
    if not isinstance(params, dict):
        raise ToolInvocationError(f"工具 {spec.name} 参数必须是对象")
    schema = spec.parameters or {}
    required = schema.get("required", [])
    missing = [name for name in required if name not in params]
    if missing:
        raise ToolInvocationError(f"工具 {spec.name} 缺少参数：{', '.join(missing)}")
    properties = schema.get("properties", {})
    if schema.get("additionalProperties") is False:
        unknown = sorted(set(params) - set(properties))
        if unknown:
            raise ToolInvocationError(f"工具 {spec.name} 存在未知参数：{', '.join(unknown)}")
    for name, value in params.items():
        definition = properties.get(name) or {}
        if value is not None and definition.get("type") and not _type_matches(value, definition["type"]):
            raise ToolInvocationError(f"工具 {spec.name} 参数 {name} 类型不正确")


class ToolRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> ToolSpec:
        if spec.name in self._specs:
            raise ValueError(f"工具已注册：{spec.name}")
        self._specs[spec.name] = spec
        return spec

    def get(self, name: str) -> ToolSpec:
        try:
            return self._specs[name]
        except KeyError as exc:
            raise ToolInvocationError(f"未注册工具：{name}") from exc

    def list_specs(self) -> list[ToolSpec]:
        return list(self._specs.values())

    def function_schemas(self) -> list[dict[str, Any]]:
        return [spec.function_schema() for spec in self._specs.values()]

    def public_specs(self) -> list[dict[str, Any]]:
        """供内部审计/调试使用，不暴露 Python handler。"""
        return [{
            "name": spec.name, "version": spec.version,
            "description": spec.description, "parameters": spec.parameters,
            "read_only": spec.read_only, "risk_level": spec.risk_level,
            "timeout_seconds": spec.timeout_seconds, "max_calls": spec.max_calls,
            "retry_policy": spec.retry_policy,
            "requires_confirmation": spec.requires_confirmation,
            "idempotent": spec.idempotent,
        } for spec in self._specs.values()]

    def invoke(self, name: str, params: dict[str, Any] | None = None, *,
               confirmed: bool = False, action_id: str | None = None) -> Any:
        spec = self.get(name)
        params = params or {}
        _validate_parameters(spec, params)
        if spec.requires_confirmation and not confirmed:
            raise ToolInvocationError(f"工具 {name} 需要用户确认")

        state = _budget.get()
        if state is None:
            state = {"total": 0, "by_tool": {}}
            token = _budget.set(state)
        else:
            token = None
        tool_call_id = uuid.uuid4().hex
        try:
            limits = current_limits()
            if limits:
                limits.check("tool")
            total = int(state["total"])
            per_tool = int(state["by_tool"].get(name, 0))
            if total >= settings.tool_max_calls or per_tool >= spec.max_calls:
                record_event("tool", name, status="error", tool_call_id=tool_call_id,
                             action_id=action_id, metadata={
                                 "version": spec.version, "budget_exhausted": True,
                                 "total_calls": total, "tool_calls": per_tool,
                             }, error="tool_call_budget_exhausted")
                raise ToolInvocationError(f"工具调用预算已耗尽：{name}")
            state["total"] = total + 1
            state["by_tool"][name] = per_tool + 1
            metadata = {
                "version": spec.version, "risk_level": spec.risk_level,
                "read_only": spec.read_only, "idempotent": spec.idempotent,
                "timeout_seconds": spec.timeout_seconds,
                "parameters": params,
            }
            with trace_span("tool", name, metadata=metadata,
                            tool_call_id=tool_call_id, action_id=action_id):
                with registry_tool_call(tool_call_id):
                    return spec.handler(**params)
        finally:
            if token is not None:
                _budget.reset(token)


def _search_pois(**params: Any) -> dict[str, Any]:
    # 运行时导入，确保测试 monkeypatch 和应用热更新仍作用于真实工具函数。
    from app.agent import tools
    city = params["city"]
    # 景点和餐饮检索彼此独立；并行执行可把高德/RAG 的等待从串行叠加
    # 降为单次最长等待。两者仍由同一个只读 Registry 工具统一审计。
    with ThreadPoolExecutor(max_workers=3, thread_name_prefix="poi-search") as pool:
        attractions_future = pool.submit(
            tools.search_attractions, city, params.get("preferences", []), params.get("limit", 30))
        foods_future = pool.submit(tools.search_foods, city, params.get("food_limit", 10))
        consumption_future = pool.submit(tools.get_consumption, city)
        return {
            "attractions": attractions_future.result(),
            "foods": foods_future.result(),
            "consumption": consumption_future.result(),
        }


def _search_hotel_options(**params: Any) -> list[dict]:
    from app.agent import tools
    return tools.search_hotels(params["city"], params.get("limit", 6))


def _get_route_matrix(**params: Any) -> dict:
    from app.agent.route_service import get_route_matrix
    return get_route_matrix(params["items"], mode=params.get("mode", settings.route_mode))


def _find_nearby_pois(**params: Any) -> list[dict]:
    from app.agent.tools import find_nearby_pois
    return find_nearby_pois(
        params["city"], name=params.get("name"),
        latitude=params.get("latitude"), longitude=params.get("longitude"),
        limit=params.get("limit", 5), radius_m=params.get("radius_m"),
        category=params.get("category"),
    )


registry = ToolRegistry()
registry.register(ToolSpec(
    name="search_pois", version="1.0", description="检索目的地景点、餐饮、酒店和消费信息",
    parameters={"type": "object", "properties": {
        "city": {"type": "string"}, "preferences": {"type": "array"},
        "limit": {"type": "integer"}, "food_limit": {"type": "integer"},
        "hotel_limit": {"type": "integer"}}, "required": ["city"],
        "additionalProperties": False}, read_only=True, risk_level="low",
    timeout_seconds=15, max_calls=2, retry_policy={"max_retries": 1},
    requires_confirmation=False, idempotent=True, handler=_search_pois))
registry.register(ToolSpec(
    name="search_hotel_options", version="1.0", description="检索可枚举的酒店候选",
    parameters={"type": "object", "properties": {
        "city": {"type": "string"}, "limit": {"type": "integer"}},
        "required": ["city"], "additionalProperties": False}, read_only=True,
    risk_level="low", timeout_seconds=10, max_calls=3,
    retry_policy={"max_retries": 1}, requires_confirmation=False, idempotent=True,
    handler=_search_hotel_options))
registry.register(ToolSpec(
    name="get_route_matrix", version="1.0", description="获取同日地点之间的交通时间矩阵",
    parameters={"type": "object", "properties": {
        "items": {"type": "array"}, "mode": {"type": "string"}},
        "required": ["items"], "additionalProperties": False}, read_only=True,
    # 逐日构建矩阵：最长行程（MAX_TRIP_DAYS 天）在"校验→修复"循环下最多
    # 被调用 4 轮（多日：reflect 2 次 + format 1 次；单日：3 次 + format 1 次），
    # 预算必须覆盖该最坏情况，否则开启路线服务后 4 天以上行程必然超预算报错。
    risk_level="low", timeout_seconds=8, max_calls=4 * MAX_TRIP_DAYS,
    retry_policy={"max_retries": 0}, requires_confirmation=False, idempotent=True,
    handler=_get_route_matrix))
registry.register(ToolSpec(
    name="find_nearby_pois", version="1.0",
    description="在权威知识库中查找给定坐标或地点名称附近（同城）的真实 POI 近邻",
    parameters={"type": "object", "properties": {
        "city": {"type": "string"}, "name": {"type": "string"},
        "latitude": {"type": "number"}, "longitude": {"type": "number"},
        "limit": {"type": "integer"}, "radius_m": {"type": "integer"},
        "category": {"type": "string"}},
        "required": ["city"], "additionalProperties": False}, read_only=True,
    risk_level="low", timeout_seconds=5, max_calls=8,
    retry_policy={"max_retries": 0}, requires_confirmation=False, idempotent=True,
    handler=_find_nearby_pois))
