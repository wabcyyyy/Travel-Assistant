"""CH1 intake 升级：clarify 多轮收集器的分支行为（LLM 全 mock，不打真实模型）。"""

from app.agent.editing import clarify as clarify_mod
from app.schemas.trip import MAX_TRIP_DAYS, ClarifyRequest, ClarifyResponse


class _FakeClient:
    """签名对齐 llm_client.complete 的最小桩。"""

    def __init__(self, raw: str | Exception) -> None:
        self._raw = raw

    def complete(self, prompt: str, system_prompt: str = "", temperature: float = 0) -> str:
        if isinstance(self._raw, Exception):
            raise self._raw
        return self._raw


def _run(monkeypatch, raw: str | Exception, slots: dict | None = None) -> ClarifyResponse:
    monkeypatch.setattr(clarify_mod, "get_llm_client", lambda: _FakeClient(raw))
    return clarify_mod.run_clarify(ClarifyRequest(message="想去玩", slots=slots or {}))


def test_merges_slots_and_reports_ready(monkeypatch) -> None:
    raw = '{"city":"成都","origin_city":"北京","days":3,"persons":2,"budget":3000,"question":null,"options":null}'
    res = _run(monkeypatch, raw, slots={"city": "成都"})
    assert res.ready is True
    assert res.blocked is False
    assert res.question is None
    assert res.options == []
    assert res.slots["origin_city"] == "北京"
    assert res.slots["days"] == 3


def test_passes_through_llm_question_and_options(monkeypatch) -> None:
    raw = '{"city":null,"days":null,"persons":null,"question":"几个人一起出发呀？","options":["2 人","4 人","一家人"]}'
    res = _run(monkeypatch, raw)
    assert res.ready is False
    assert res.missing == ["city", "days", "persons"]
    assert res.question == "几个人一起出发呀？"
    assert res.options == ["2 人", "4 人", "一家人"]


def test_llm_failure_falls_back_to_template(monkeypatch) -> None:
    res = _run(monkeypatch, RuntimeError("llm down"))
    assert res.ready is False
    assert res.blocked is False
    assert res.question == "还想确认一下目的地城市～"
    assert res.options == ["帮我推荐目的地"]


def test_unparseable_llm_output_keeps_old_slots(monkeypatch) -> None:
    res = _run(monkeypatch, "我觉得你说得对", slots={"city": "成都"})
    assert res.slots["city"] == "成都"
    assert res.missing == ["days", "persons"]
    assert res.question == "还想确认一下出行天数～"
    assert res.options == ["3 天", "5 天", "7 天"]


def test_overlong_days_blocks_instead_of_truncating(monkeypatch) -> None:
    raw = '{"city":"成都","days":14,"persons":2,"question":null,"options":null}'
    res = _run(monkeypatch, raw)
    assert res.blocked is True
    assert res.ready is False
    assert res.slots["days"] == 14, "上限不静默截断：天数原样保留，由对话协商"
    assert res.question is not None and "7 天" in res.question
    assert res.options == [f"改成 {MAX_TRIP_DAYS} 天以内", "拆成两段行程"]


def test_overlong_days_uses_llm_negotiation_copy(monkeypatch) -> None:
    raw = (
        '{"city":"成都","days":14,"persons":2,'
        '"question":"最多只能排 7 天哦，要不要拆成两段？","options":["拆两段","改 7 天"]}'
    )
    res = _run(monkeypatch, raw)
    assert res.blocked is True
    assert res.question is not None and res.question.startswith("最多只能排 7 天")
    assert res.options == ["拆两段", "改 7 天"]


def test_nonpositive_or_wordy_numbers_are_reasked(monkeypatch) -> None:
    raw = '{"city":"成都","days":0,"persons":"两周","budget":3000}'
    res = _run(monkeypatch, raw)
    assert "days" in res.missing and "persons" in res.missing
    assert res.ready is False
    assert "days" not in res.slots and "persons" not in res.slots


def test_options_capped_at_four(monkeypatch) -> None:
    raw = '{"city":null,"question":"去哪？","options":["a","b","c","d","e"]}'
    res = _run(monkeypatch, raw)
    assert len(res.options) == 4
