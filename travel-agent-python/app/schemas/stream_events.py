"""跨语言流事件契约：generate-stream 的 JSON Lines 事件模型（单一模型源）。

职责：
- 为整段流式生成的六类事件（start / day / day_patch / suggestions / done / error）
  定义唯一模型；Python 产出点一律「模型构造 → dump」输出 wire dict，
  杜绝手搓键名漂移；
- export_schema() 导出联合 JSON Schema（仓库根 contracts/stream_events.schema.json），
  供 Java 侧运行时校验与 CI 漂移比对。

实现要点：
- 字段与既有 wire 形状严格一致：camelCase 由 WireModel 别名生成
  （run_id→runId、days_expected→daysExpected 等）；
- 嵌套 plan/items 复用 trip 契约模型（DailyPlan/Suggestion），
  嵌套字段（dayNo/poiName/...）由它们定义，不在此重复声明；
- type 用 Literal 判别（discriminated union），schema 导出为 oneOf + const，
  Java 侧可对未知类型做前向兼容忽略；
- 导出前剥离 description：docstring 只服务 Python 可读性，不应触发契约漂移。
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, TypeAdapter

from app.schemas.common import WireModel
from app.schemas.trip import DailyPlan, Suggestion


class StartEvent(WireModel):
    type: Literal["start"]
    run_id: str


class DayEvent(WireModel):
    type: Literal["day"]
    plan: DailyPlan


class DayPatchEvent(WireModel):
    """酒店摊铺等确定性修补后的单天重发（Java 按 overwrite 落库）。"""

    type: Literal["day_patch"]
    plan: DailyPlan


class SuggestionsEvent(WireModel):
    type: Literal["suggestions"]
    items: list[Suggestion]


class DoneEvent(WireModel):
    type: Literal["done"]
    days_expected: int
    days_emitted: list[int]
    trip_theme: str | None
    complete: bool
    message: str | None


class ErrorEvent(WireModel):
    type: Literal["error"]
    message: str


StreamEvent = Annotated[
    StartEvent | DayEvent | DayPatchEvent | SuggestionsEvent | DoneEvent | ErrorEvent,
    Field(discriminator="type"),
]

_EVENT_ADAPTER = TypeAdapter(StreamEvent)

_NAME_MAPS = frozenset({"properties", "patternProperties", "$defs", "definitions"})


def to_wire(event: BaseModel) -> dict:
    """事件模型 → JSON Lines 的 wire dict（camelCase）。"""
    return event.model_dump(mode="json", by_alias=True)


def _strip_descriptions(node: object) -> None:
    if isinstance(node, dict):
        for key in list(node.keys()):
            if key == "description":
                del node[key]
                continue
            value = node[key]
            if key in _NAME_MAPS and isinstance(value, dict):
                for sub in value.values():
                    _strip_descriptions(sub)
            else:
                _strip_descriptions(value)
    elif isinstance(node, list):
        for item in node:
            _strip_descriptions(item)


def _mark_all_properties_required(node: object) -> None:
    """wire 语义：模型 dump 必然携带全部键（可空值以 null 出现）。

    Pydantic 的 required 表达「构造必填」，弱于 wire 事实——仅按它导出时，
    可选字段改名不会触发校验，Java 侧仍会静默落 null。这里把每个对象
    schema 的 required 提升为全部 properties。
    """
    if isinstance(node, dict):
        props = node.get("properties")
        if isinstance(props, dict) and props:
            node["required"] = list(props)
        for key, value in node.items():
            if key in _NAME_MAPS and isinstance(value, dict):
                for sub in value.values():
                    _mark_all_properties_required(sub)
            else:
                _mark_all_properties_required(value)
    elif isinstance(node, list):
        for item in node:
            _mark_all_properties_required(item)


def export_schema() -> dict:
    """导出事件联合的 JSON Schema（含 $defs 嵌套契约，顺序确定可做字节比对）。"""
    schema = _EVENT_ADAPTER.json_schema()
    _strip_descriptions(schema)
    _mark_all_properties_required(schema)
    return schema
