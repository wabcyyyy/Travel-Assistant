import pytest

from app.agent.tool_registry import (
    ToolInvocationError,
    ToolRegistry,
    ToolSpec,
    begin_tool_budget,
    end_tool_budget,
)
from app.agent.trace import trace_run
from app.common.config import settings


def _spec(name="demo", handler=lambda **params: params, max_calls=2):
    return ToolSpec(
        name=name,
        version="1.0",
        description="demo",
        parameters={
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
            "additionalProperties": False,
        },
        read_only=True,
        risk_level="low",
        timeout_seconds=1,
        max_calls=max_calls,
        retry_policy={"max_retries": 0},
        requires_confirmation=False,
        idempotent=True,
        handler=handler,
    )


def test_registry_exposes_only_registered_schemas_and_validates_arguments():
    registry = ToolRegistry()
    registry.register(_spec())
    assert registry.function_schemas()[0]["function"]["name"] == "demo"
    assert registry.invoke("demo", {"city": "杭州"})["city"] == "杭州"
    with pytest.raises(ToolInvocationError, match="未注册"):
        registry.invoke("missing", {})
    with pytest.raises(ToolInvocationError, match="未知参数"):
        registry.invoke("demo", {"city": "杭州", "token": "secret"})


def test_registry_records_tool_call_id_and_enforces_request_budget(monkeypatch):
    monkeypatch.setattr(settings, "tool_max_calls", 1)
    registry = ToolRegistry()
    registry.register(_spec(max_calls=5))
    with trace_run("run", "request") as trace:
        token = begin_tool_budget()
        try:
            registry.invoke("demo", {"city": "杭州"}, action_id="day-1")
            with pytest.raises(ToolInvocationError, match="预算"):
                registry.invoke("demo", {"city": "杭州"})
        finally:
            end_tool_budget(token)
    event = trace.to_dict()["events"][0]
    assert event["request_id"] == "request"
    assert event["tool_call_id"]
    assert event["action_id"] == "day-1"
    assert event["metadata"]["version"] == "1.0"
