"""受控工具目录（唯一注册表，G-1.4）。

工具只能通过显式注册后执行，目录同时提供 Function Calling schema、参数校验、
调用预算和脱敏审计事件。写入型工具默认不注册，避免模型或不可信工具结果
绕过业务服务直接改变行程状态。全部工具面（含 research 三域检索）统一从
本注册表派发，禁止 getattr 字符串派发散落各处。

handler 约定：经 `from app.agent import tools` 后**调用期**读模块属性
（`tools.search_attractions(...)`），保证 mock.patch.object(tools, ...) 零
修改生效；不得在注册期绑定函数对象。
"""

from __future__ import annotations

import contextvars
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from app.agent.run_limits import current_limits
from app.agent.trace import record_event, registry_tool_call, trace_span
from app.common.addons import addons
from app.common.config import settings
from app.schemas.trip import MAX_TRIP_DAYS


class ToolInvocationError(ValueError):
    """工具不存在、参数不合法、未确认或超过预算。"""


@dataclass(frozen=True)
class RunContext:
    """工具门控的评估上下文。

    G-1.4 只建立机制（ToolSpec.when + 本上下文），消费方（addon/feature-flag
    体系）在 G-3.1 接线；当前所有 spec 的 when 均为 None，行为零变化。
    """

    name: str
    params: dict[str, Any] = field(default_factory=dict)


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
    # 运行时门控钩子：返回 False 时该工具按「未注册」处理（隐藏而非报错）。
    # None 表示无条件可用。评估入参见 RunContext。
    when: Callable[[RunContext], bool] | None = None

    def function_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


_budget: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar("agent_tool_budget", default=None)


def begin_tool_budget() -> contextvars.Token:
    return _budget.set({"total": 0, "by_tool": {}})


def end_tool_budget(token: contextvars.Token) -> None:
    _budget.reset(token)


def tool_budget_snapshot() -> dict[str, Any]:
    current = _budget.get() or {"total": 0, "by_tool": {}}
    return {"total": int(current.get("total", 0)), "by_tool": dict(current.get("by_tool", {}))}


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
        """当前可用的工具（when 门控关闭的不列——工具面随能力收起，G-3.1）。"""
        return [spec for spec in self._specs.values() if self._visible(spec)]

    @staticmethod
    def _visible(spec: ToolSpec) -> bool:
        return spec.when is None or spec.when(RunContext(name=spec.name))

    def function_schemas(self) -> list[dict[str, Any]]:
        """Function Calling schema：同样只列 when 门控放行的工具（LLM 不见被关能力）。"""
        return [spec.function_schema() for spec in self.list_specs()]

    def public_specs(self) -> list[dict[str, Any]]:
        """供内部审计/调试使用，不暴露 Python handler。"""
        return [
            {
                "name": spec.name,
                "version": spec.version,
                "description": spec.description,
                "parameters": spec.parameters,
                "read_only": spec.read_only,
                "risk_level": spec.risk_level,
                "timeout_seconds": spec.timeout_seconds,
                "max_calls": spec.max_calls,
                "retry_policy": spec.retry_policy,
                "requires_confirmation": spec.requires_confirmation,
                "idempotent": spec.idempotent,
            }
            for spec in self.list_specs()
        ]

    def invoke(
        self, name: str, params: dict[str, Any] | None = None, *, confirmed: bool = False, action_id: str | None = None
    ) -> Any:
        spec = self.get(name)
        params = params or {}
        # 门控钩子（G-1.4 机制，G-3.1 接消费方）：关闭的工具与未注册工具同话术，
        # 不暴露「存在但被禁用」；先于参数校验，被禁用即不存在。
        if spec.when is not None and not spec.when(RunContext(name=name, params=dict(params))):
            raise ToolInvocationError(f"未注册工具：{name}")
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
                record_event(
                    "tool",
                    name,
                    status="error",
                    tool_call_id=tool_call_id,
                    action_id=action_id,
                    metadata={
                        "version": spec.version,
                        "budget_exhausted": True,
                        "total_calls": total,
                        "tool_calls": per_tool,
                    },
                    error="tool_call_budget_exhausted",
                )
                raise ToolInvocationError(f"工具调用预算已耗尽：{name}")
            state["total"] = total + 1
            state["by_tool"][name] = per_tool + 1
            metadata = {
                "version": spec.version,
                "risk_level": spec.risk_level,
                "read_only": spec.read_only,
                "idempotent": spec.idempotent,
                "timeout_seconds": spec.timeout_seconds,
                "parameters": params,
            }
            with (
                trace_span("tool", name, metadata=metadata, tool_call_id=tool_call_id, action_id=action_id),
                registry_tool_call(tool_call_id),
            ):
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
            tools.search_attractions, city, params.get("preferences", []), params.get("limit", 30)
        )
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
        params["city"],
        name=params.get("name"),
        latitude=params.get("latitude"),
        longitude=params.get("longitude"),
        limit=params.get("limit", 5),
        radius_m=params.get("radius_m"),
        category=params.get("category"),
    )


# ---- G-1.4：tools.py 全部工具函数入册（handler 一律调用期经 tools 模块属性
# 解析真实函数——`tools.xxx(...)` 晚绑定，mock.patch.object 零修改生效）----


def _search_local_poi_handler(**params: Any) -> list[dict]:
    from app.agent import tools

    return tools.search_local_poi(params["city"], params["name"], category=params.get("category"))


def _search_attractions_handler(**params: Any) -> list[dict]:
    from app.agent import tools

    return tools.search_attractions(params["city"], params.get("preferences") or [], params.get("limit", 30))


def _search_foods_handler(**params: Any) -> list[dict]:
    from app.agent import tools

    return tools.search_foods(params["city"], params.get("limit", 10))


def _search_hotels_handler(**params: Any) -> list[dict]:
    from app.agent import tools

    return tools.search_hotels(params["city"], params.get("limit", 6))


def _get_poi_detail_handler(**params: Any) -> dict | None:
    from app.agent import tools

    return tools.get_poi_detail(params["city"], params["name"])


def _get_consumption_handler(**params: Any) -> dict | None:
    from app.agent import tools

    return tools.get_consumption(params["city"])


def _search_hotel_room_types_handler(**params: Any) -> list[dict]:
    from app.agent import tools

    return tools.search_hotel_room_types(params["poi_ids"])


def _poi_image_handler(**params: Any) -> str | None:
    from app.agent import tools

    return tools.poi_image(params.get("name"), params["city"])


def _attach_poi_images_handler(**params: Any) -> list[dict]:
    from app.agent import tools

    return tools.attach_poi_images(params["plan"], params["city"])


def _web_search_places_handler(**params: Any) -> list[dict]:
    # INV-9：外部调用必须有超时与响应上限——search_places_via_web 走 llm_client
    # （自带超时/上限/预算检查 _check_budget），非裸 httpx。
    from app.agent.web_search import search_places_via_web

    return search_places_via_web(
        params["city"],
        params["category"],
        limit=params.get("limit", 4),
        budget_tier=params.get("budget_tier"),
        intent_keywords=params.get("intent_keywords") or [],
    )


registry = ToolRegistry()
registry.register(
    ToolSpec(
        name="search_pois",
        version="1.0",
        description="检索目的地景点、餐饮、酒店和消费信息",
        parameters={
            "type": "object",
            "properties": {
                "city": {"type": "string"},
                "preferences": {"type": "array"},
                "limit": {"type": "integer"},
                "food_limit": {"type": "integer"},
                "hotel_limit": {"type": "integer"},
            },
            "required": ["city"],
            "additionalProperties": False,
        },
        read_only=True,
        risk_level="low",
        timeout_seconds=15,
        max_calls=2,
        retry_policy={"max_retries": 1},
        requires_confirmation=False,
        idempotent=True,
        handler=_search_pois,
    )
)
registry.register(
    ToolSpec(
        name="search_hotel_options",
        version="1.0",
        description="检索可枚举的酒店候选",
        parameters={
            "type": "object",
            "properties": {"city": {"type": "string"}, "limit": {"type": "integer"}},
            "required": ["city"],
            "additionalProperties": False,
        },
        read_only=True,
        risk_level="low",
        timeout_seconds=10,
        max_calls=3,
        retry_policy={"max_retries": 1},
        requires_confirmation=False,
        idempotent=True,
        handler=_search_hotel_options,
    )
)
registry.register(
    ToolSpec(
        name="get_route_matrix",
        version="1.0",
        description="获取同日地点之间的交通时间矩阵",
        parameters={
            "type": "object",
            "properties": {"items": {"type": "array"}, "mode": {"type": "string"}},
            "required": ["items"],
            "additionalProperties": False,
        },
        read_only=True,
        # 逐日构建矩阵：最长行程（MAX_TRIP_DAYS 天）在"校验→修复"循环下最多
        # 被调用 4 轮（多日：reflect 2 次 + format 1 次；单日：3 次 + format 1 次），
        # 预算必须覆盖该最坏情况，否则开启路线服务后 4 天以上行程必然超预算报错。
        risk_level="low",
        timeout_seconds=8,
        max_calls=4 * MAX_TRIP_DAYS,
        retry_policy={"max_retries": 0},
        requires_confirmation=False,
        idempotent=True,
        handler=_get_route_matrix,
    )
)
registry.register(
    ToolSpec(
        name="find_nearby_pois",
        version="1.0",
        description="在权威知识库中查找给定坐标或地点名称附近（同城）的真实 POI 近邻",
        parameters={
            "type": "object",
            "properties": {
                "city": {"type": "string"},
                "name": {"type": "string"},
                "latitude": {"type": "number"},
                "longitude": {"type": "number"},
                "limit": {"type": "integer"},
                "radius_m": {"type": "integer"},
                "category": {"type": "string"},
            },
            "required": ["city"],
            "additionalProperties": False,
        },
        read_only=True,
        risk_level="low",
        timeout_seconds=5,
        max_calls=8,
        retry_policy={"max_retries": 0},
        requires_confirmation=False,
        idempotent=True,
        handler=_find_nearby_pois,
    )
)


registry.register(
    ToolSpec(
        name="search_local_poi",
        version="1.0",
        description="按名称在权威知识库解析单个本地 POI（补查/grounding 用）",
        parameters={
            "type": "object",
            "properties": {"city": {"type": "string"}, "name": {"type": "string"}, "category": {"type": "string"}},
            "required": ["city", "name"],
            "additionalProperties": False,
        },
        read_only=True,
        risk_level="low",
        timeout_seconds=5,
        max_calls=16,
        retry_policy={"max_retries": 0},
        requires_confirmation=False,
        idempotent=True,
        handler=_search_local_poi_handler,
    )
)
registry.register(
    ToolSpec(
        name="search_attractions",
        version="1.0",
        description="检索目的地景点候选（RAG 向量召回 + 权威库回退）",
        parameters={
            "type": "object",
            "properties": {"city": {"type": "string"}, "preferences": {"type": "array"}, "limit": {"type": "integer"}},
            "required": ["city"],
            "additionalProperties": False,
        },
        read_only=True,
        risk_level="low",
        timeout_seconds=15,
        max_calls=8,
        retry_policy={"max_retries": 0},
        requires_confirmation=False,
        idempotent=True,
        handler=_search_attractions_handler,
    )
)
registry.register(
    ToolSpec(
        name="search_foods",
        version="1.0",
        description="检索目的地餐饮候选",
        parameters={
            "type": "object",
            "properties": {"city": {"type": "string"}, "limit": {"type": "integer"}},
            "required": ["city"],
            "additionalProperties": False,
        },
        read_only=True,
        risk_level="low",
        timeout_seconds=10,
        max_calls=8,
        retry_policy={"max_retries": 0},
        requires_confirmation=False,
        idempotent=True,
        handler=_search_foods_handler,
    )
)
registry.register(
    ToolSpec(
        name="search_hotels",
        version="1.0",
        description="检索目的地酒店候选（保留完整可枚举集）",
        parameters={
            "type": "object",
            "properties": {"city": {"type": "string"}, "limit": {"type": "integer"}},
            "required": ["city"],
            "additionalProperties": False,
        },
        read_only=True,
        risk_level="low",
        timeout_seconds=10,
        max_calls=8,
        retry_policy={"max_retries": 0},
        requires_confirmation=False,
        idempotent=True,
        handler=_search_hotels_handler,
    )
)
registry.register(
    ToolSpec(
        name="get_poi_detail",
        version="1.0",
        description="查询单个 POI 的知识库详情",
        parameters={
            "type": "object",
            "properties": {"city": {"type": "string"}, "name": {"type": "string"}},
            "required": ["city", "name"],
            "additionalProperties": False,
        },
        read_only=True,
        max_calls=8,
        risk_level="low",
        timeout_seconds=5,
        retry_policy={"max_retries": 0},
        requires_confirmation=False,
        idempotent=True,
        handler=_get_poi_detail_handler,
    )
)
registry.register(
    ToolSpec(
        name="get_consumption",
        version="1.0",
        description="查询目的地人均消费水位",
        parameters={
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
            "additionalProperties": False,
        },
        max_calls=8,
        read_only=True,
        risk_level="low",
        timeout_seconds=5,
        retry_policy={"max_retries": 0},
        requires_confirmation=False,
        idempotent=True,
        handler=_get_consumption_handler,
    )
)
registry.register(
    ToolSpec(
        name="search_hotel_room_types",
        version="1.0",
        description="按 POI id 列表查询酒店房型与价格",
        parameters={
            "type": "object",
            "properties": {"poi_ids": {"type": "array"}},
            "required": ["poi_ids"],
            "additionalProperties": False,
        },
        read_only=True,
        risk_level="low",
        timeout_seconds=5,
        max_calls=4,
        retry_policy={"max_retries": 0},
        requires_confirmation=False,
        idempotent=True,
        handler=_search_hotel_room_types_handler,
    )
)
registry.register(
    ToolSpec(
        name="poi_image",
        version="1.0",
        description="查询单个 POI 的配图 URL（本地快照优先）",
        parameters={
            "type": "object",
            "properties": {"name": {"type": "string"}, "city": {"type": "string"}},
            "required": ["city"],
            "additionalProperties": False,
        },
        read_only=True,
        risk_level="low",
        timeout_seconds=10,
        max_calls=16,
        retry_policy={"max_retries": 0},
        requires_confirmation=False,
        idempotent=True,
        handler=_poi_image_handler,
    )
)
registry.register(
    ToolSpec(
        name="attach_poi_images",
        version="1.0",
        description="为整份行程点位批量补图",
        parameters={
            "type": "object",
            "properties": {"plan": {"type": "array"}, "city": {"type": "string"}},
            "required": ["plan", "city"],
            "additionalProperties": False,
        },
        read_only=True,
        risk_level="low",
        timeout_seconds=15,
        max_calls=4,
        retry_policy={"max_retries": 0},
        requires_confirmation=False,
        idempotent=True,
        handler=_attach_poi_images_handler,
    )
)
registry.register(
    ToolSpec(
        name="web_search_places",
        version="1.0",
        description="联网补充真实地点名（证据不足时的补池通道；addon=web_search 门控）",
        parameters={
            "type": "object",
            "properties": {
                "city": {"type": "string"},
                "category": {"type": "string"},
                "limit": {"type": "integer"},
                "intent_keywords": {"type": "array"},
            },
            "required": ["city", "category"],
            "additionalProperties": False,
        },
        read_only=True,
        risk_level="medium",
        timeout_seconds=15,
        max_calls=6,
        retry_policy={"max_retries": 0},
        requires_confirmation=False,
        idempotent=True,
        handler=_web_search_places_handler,
        # G-1.4 的 when 钩子在此接线：addon 关闭 → 不列入工具面、invoke 报未注册
        when=lambda _ctx: addons.is_enabled("web_search"),
    )
)
