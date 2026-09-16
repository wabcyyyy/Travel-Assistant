"""Agent 层唯一公开面（G-1.2 边界收敛）。

约定：
- api/services 层只准 ``from app.agent import X`` 使用本导出面；深路径
  （``from app.agent.workflow import ...``）由 import-linter 门禁禁止；
- agent 层内部模块互相调用不受此限（``from app.agent.workflow import ...``
  在 agent 层内合法）；
- 新增对外能力 = 在对应子模块实现后，在此登记 re-export + ``__all__``；
- 真正跨模块共用的内部符号不走本门面，由所属模块去下划线提级为
  「跨模块 API」（见 generators/day_stream/tools/workflow 模块 docstring）。

依赖：本包各子模块；本文件不得承载业务逻辑。
"""

from app.agent.butler import run_butler_note, run_poi_intros
from app.agent.chat_draft import run_chat_turn
from app.agent.city_guide import run_city_guide
from app.agent.clarify import run_clarify
from app.agent.day_stream import run_generate_day
from app.agent.local_replan import run_local_replan
from app.agent.nl_edit import run_edit_ops
from app.agent.observability import metrics, observe_run, scene, use_scene
from app.agent.plan_context import run_plan_context
from app.agent.schedule_optimizer import optimize_daily_plan
from app.agent.tool_registry import ToolInvocationError, ToolSpec, registry
from app.agent.tools import find_nearby_pois
from app.agent.trip_stream import run_generate_trip_stream
from app.agent.usage_store import usage_store
from app.agent.workflow import run_adjust, run_generate

__all__ = [
    "ToolInvocationError",
    "ToolSpec",
    "find_nearby_pois",
    "metrics",
    "observe_run",
    "optimize_daily_plan",
    "registry",
    "run_adjust",
    "run_butler_note",
    "run_chat_turn",
    "run_city_guide",
    "run_clarify",
    "run_edit_ops",
    "run_generate",
    "run_generate_day",
    "run_generate_trip_stream",
    "run_local_replan",
    "run_plan_context",
    "run_poi_intros",
    "scene",
    "usage_store",
    "use_scene",
]
