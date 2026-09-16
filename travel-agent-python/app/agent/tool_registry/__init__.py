"""受控工具目录（包）：core = 机制，catalog = 登记（G-2.6 按域拆包）。

公开面（re-export，消费者零改动）：registry / ToolSpec / ToolInvocationError /
RunContext / begin_tool_budget / end_tool_budget / tool_budget_snapshot。
导入本包即完成全部工具登记（__init__ 末尾导入 catalog）。
"""

from app.agent.tool_registry import catalog
from app.agent.tool_registry.core import (
    RunContext,
    ToolInvocationError,
    ToolRegistry,
    ToolSpec,
    begin_tool_budget,
    end_tool_budget,
    registry,
    tool_budget_snapshot,
)

__all__ = [
    "RunContext",
    "ToolInvocationError",
    "ToolRegistry",
    "ToolSpec",
    "begin_tool_budget",
    "catalog",
    "end_tool_budget",
    "registry",
    "tool_budget_snapshot",
]
