"""逐日生成门面：编排已合并进 trip_graph 统一图。

历史 day_workflow 自带 StateGraph；现与整段生成共用
``trip_graph.unified_agent_graph``（mode=day）。
本模块保留 ``_generate_day_once`` 再导出，便于测试 monkeypatch；
``run_day_agent`` 为兼容入口，HTTP 层仍经 ``day_stream.run_generate_day`` 调用。
"""

from app.agent.day_stream import _generate_day_once  # noqa: F401
from app.schemas.trip import DailyPlan, GenerateDayRequest


def run_day_agent(req: GenerateDayRequest) -> DailyPlan:
    from app.agent.trip_graph import run_day
    return run_day(req)


# 兼容旧名：测试/脚本若仍 import build_day_graph / day_agent_graph
def build_day_graph():
    from app.agent.trip_graph import unified_agent_graph
    return unified_agent_graph


day_agent_graph = None  # 惰性；请用 trip_graph.unified_agent_graph
