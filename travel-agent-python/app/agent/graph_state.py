"""统一图（整段）的状态定义（G-2.4 自 workflow 拆出）。

放在中立模块：图节点（graph_nodes）与输出装配（formatting.assembly）都要引用
本类型，放任一侧都会造成循环导入。

依赖：仅 schemas.trip 的契约模型。
"""

from typing import NotRequired, TypedDict

from app.schemas.trip import GenerateRequest, GenerateResponse


class AgentState(TypedDict):
    request: GenerateRequest
    requirements: dict
    candidates: list[dict]
    foods: list[dict]
    hotels: list[dict]
    consumption: dict | None
    # 城市级天气（C3.1）：仅 research 节点写入；NotRequired 因为图节点返回的是
    # 部分状态增量，其他节点/测试构造的部分 state 不必携带该键。
    weather: NotRequired[list[dict] | None]
    daily_plans: list[dict]
    budget_estimate: dict
    raw_suggestions: list[dict]
    result: GenerateResponse
    attempts: int
    fix_count: int
    error: str | None
    feedback: str
    validation_issues: list[str]
    validation_log: list[str]
    degraded_reason: str | None
    schedule_report: dict
    critic_report: dict
    research_report: dict
    refill_count: int
