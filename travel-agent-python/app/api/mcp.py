"""MCP 出口（G-3.6）：把已注册的只读工具暴露给外部 MCP 客户端。

设计口径：
- **只读工具面**：从 tool_registry 里挑 `read_only=True` 的工具（写路径——如
  apply/delete 类——一律不暴露；外部客户端只能查，不能改行程）；
- **描述与参数 schema 由 ToolSpec 自动生成**：工具的 description 与 parameters
  都取自注册表（ToolSpec 是单一真源），MCP 侧不维护第二份，避免两处漂移；
- **鉴权**：`AGENT_INTERNAL_TOKEN`（Bearer 或 X-Agent-Token）。与 HTTP 直调
  agent 面同一把令牌——不做 OAuth、不做访问策略矩阵（卡内明确否决）；
- **门控**：`require_addon("mcp")`——addon 关闭时整个 /mcp 路径 404（隐藏而非
  403），默认**关闭**（安全默认：出口能力要显式打开）；
- 调用一律经 `registry.invoke`：预算、参数校验、审计事件与内部工具调用同一套，
  不存在"外部调用绕过治理"的第二条路径。

依赖：mcp（FastMCP）、app.agent.tool_registry、app.common.{addons,config,envelope}。
"""

from __future__ import annotations

import inspect
import logging
from typing import Any

from mcp.server.fastmcp import FastMCP

from app.agent import ToolInvocationError, ToolSpec, registry
from app.common.addons import addons
from app.common.config import settings

logger = logging.getLogger(__name__)

#: 对外暴露的工具白名单：只读、且对外部消费方有意义的入口。
#: 有意不含 poi_image / attach_poi_images（图片 URL 对本仓无外部价值）与
#: web_search_places（外部调用成本高，且它已由 web_search addon 单独门控）。
EXPOSED_TOOLS: tuple[str, ...] = (
    "search_pois",
    "search_attractions",
    "search_foods",
    "search_hotels",
    "find_nearby_pois",
    "get_route_matrix",
    "get_poi_detail",
    "get_consumption",
)

_JSON_TO_PY: dict[str, type] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list,
    "object": dict,
}


def _py_type(json_type: str) -> type:
    """JSON Schema 类型 → Python 类型（FastMCP 从签名推断，必须给真实类型）。

    不能用 `Any` 占位：FastMCP 会对注解做 `issubclass(annotation, Context)`，
    拿到字符串注解会直接 TypeError（实测）。
    """
    return _JSON_TO_PY.get(json_type, str)


def _signature_from_schema(schema: dict[str, Any]) -> inspect.Signature:
    """按 ToolSpec.parameters 造精确签名（required 无默认、可选默认 None）。"""
    properties: dict[str, Any] = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    parameters: list[inspect.Parameter] = []
    for name, definition in properties.items():
        annotation = _py_type(str((definition or {}).get("type") or "string"))
        if name in required:
            parameters.append(inspect.Parameter(name, inspect.Parameter.KEYWORD_ONLY, annotation=annotation))
        else:
            parameters.append(
                inspect.Parameter(name, inspect.Parameter.KEYWORD_ONLY, annotation=annotation | None, default=None)
            )
    return inspect.Signature(parameters)


def _handler_for(spec: ToolSpec):
    """为 spec 造一个调用期经注册表派发的 handler（预算/校验/审计全覆盖）。"""

    def _call(**params: Any) -> Any:
        try:
            return registry.invoke(spec.name, params)
        except ToolInvocationError as exc:
            # 工具级失败（预算/参数/未注册）如实上抛给 MCP 客户端，不吞成空结果
            raise ValueError(str(exc)) from exc

    _call.__name__ = spec.name
    _call.__doc__ = spec.description
    # 签名按注册表 schema 生成：既让 FastMCP 的类型检查通过，也让"参数长什么样"
    # 由注册表决定（下方还会用 ToolSpec.parameters 覆盖一遍最终 schema）。
    _call.__signature__ = _signature_from_schema(spec.parameters)  # type: ignore[attr-defined]
    return _call


def exposed_specs() -> list[ToolSpec]:
    """当前可暴露的只读工具（受 addon 与注册表 when 门控共同影响）。"""
    available = {spec.name: spec for spec in registry.list_specs() if spec.read_only}
    return [available[name] for name in EXPOSED_TOOLS if name in available]


def _apply_schema(server: FastMCP, spec: ToolSpec) -> None:
    """把 ToolSpec.parameters 注回 FastMCP 的工具对象（schema 单一真源在注册表）。

    FastMCP 默认从函数签名推断 schema；这里用注册表的 JSON Schema 覆盖，
    保证"对外契约 = 内部治理元数据"（改 ToolSpec 即改对外契约，一处生效）。
    """
    tool = server._tool_manager.get_tool(spec.name)
    if tool is None:
        return
    tool.parameters = spec.parameters


def build_server() -> FastMCP:
    """构建 MCP 服务实例（每次调用新建，便于测试与热更新 addon 状态）。"""
    server = FastMCP(
        name="travel-assistant",
        instructions=(
            "只读旅行数据工具面：检索本地权威 POI 库、查询同城近邻、估算路线时间矩阵。"
            "数据来自本地知识库，不访问第三方地理服务。"
        ),
    )
    for spec in exposed_specs():
        server.add_tool(_handler_for(spec), name=spec.name, description=spec.description)
        _apply_schema(server, spec)
    return server


async def list_tool_names() -> list[str]:
    """对外可见的工具名（供自检与测试；与 build_server 同一取数口径）。"""
    return [spec.name for spec in exposed_specs()]


def _authorized(headers: dict[bytes, bytes]) -> bool:
    """`AGENT_INTERNAL_TOKEN` 校验（Bearer 或 X-Agent-Token，二选一）。"""
    expected = settings.agent_internal_token
    if not expected:
        # 未配置令牌时与 HTTP 直调面同口径：仅回环部署可匿名（见 main 的启动校验）
        return True
    raw = (headers.get(b"authorization") or headers.get(b"x-agent-token") or b"").decode("latin-1").strip()
    token = raw[7:].strip() if raw.lower().startswith("bearer ") else raw
    return token == expected


class McpGate:
    """ASGI 包装：addon 门控（未开启即 404）+ 令牌校验（不通过即 401）。"""

    def __init__(self, app: Any) -> None:
        self._app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self._app(scope, receive, send)
            return
        if not addons.is_enabled("mcp"):
            await self._reject(send, 404, b"Not Found")
            return
        if not _authorized({k.lower(): v for k, v in (scope.get("headers") or [])}):
            await self._reject(send, 401, b"Unauthorized")
            return
        await self._app(scope, receive, send)

    @staticmethod
    async def _reject(send: Any, status: int, body: bytes) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [(b"content-type", b"text/plain; charset=utf-8")],
            }
        )
        await send({"type": "http.response.body", "body": body})


def mcp_asgi_app() -> Any:
    """挂载用 ASGI app（含门控）；addon 状态在每次请求时实时判定。"""
    return McpGate(build_server().streamable_http_app())
