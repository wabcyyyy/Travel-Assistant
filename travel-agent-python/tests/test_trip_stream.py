"""整段流式生成（trip_stream）单元测试。

覆盖：
- DailyPlansStreamParser：整块/逐字符喂入一致性、字符串内花括号与转义、
  截断流的部分产出、trip_theme/suggestions 收割；
- generation_core 去重：归一化名称变体、近坐标双通道、酒店豁免；
- run_generate_trip_stream：事件序列（day/day_patch/suggestions/done）、
  跨天重复丢弃、城市不符建议过滤。
"""

import json

import pytest

from app.agent.generation_core import (
    PoiSeenRegistry,
    drop_cross_day_duplicates,
    haversine_m,
    norm_poi_key,
)
from app.agent.trip_stream import (
    DailyPlansStreamParser,
    _filter_suggestions_by_city,
    run_generate_trip_stream,
)
from app.common.config import settings
from app.schemas.trip import GenerateDayRequest


TRIP_JSON = (
    '{"trip_theme":"巴塞罗那·高迪之光","daily_plans":['
    '{"day_no":1,"theme":"高迪代表作日：圣家堂与格拉西亚大道","note":"经典地标日",'
    '"items":[{"item_type":"attraction","poi_name":"圣家堂（Sagrada Família）",'
    '"latitude":41.4036,"longitude":2.1744,'
    '"start_time":"09:00","end_time":"11:30","cost":26,"tag":"地标","why_this":"必看","refs":[1]},'
    '{"item_type":"hotel","poi_name":"文华东方酒店巴塞罗那","start_time":"15:00","end_time":"23:00","cost":1800}]}'
    ',{"day_no":2,"theme":"哥特区漫游","note":"老城历史",'
    '"items":[{"item_type":"attraction","poi_name":"巴塞罗那大教堂",'
    '"start_time":"10:00","end_time":"11:00","cost":9,"tag":"人文","why_this":"哥特区核心"},'
    '{"item_type":"food","poi_name":"Los Toreros","start_time":"13:00","end_time":"14:00","cost":35}]}'
    ',{"day_no":3,"theme":"再访圣家堂周边","note":"补漏",'
    '"items":[{"item_type":"attraction","poi_name":"圣家堂大教堂",'
    '"latitude":41.40362,"longitude":2.17438,'
    '"start_time":"09:30","end_time":"11:00","cost":26,"tag":"地标","why_this":"变体重复"},'
    '{"item_type":"attraction","poi_name":"古埃尔公园","start_time":"14:00","end_time":"16:00","cost":10}]}'
    '],"suggestions":['
    '{"poi_name":"米拉之家","city":"巴塞罗那","category":"attraction","intro":"高迪代表作之一","need_reservation":true,"estimated_cost":24},'
    '{"poi_name":"唐吉诃德涩谷","city":"东京","category":"shopping","intro":"东京连锁免税店","need_reservation":false}'
    ']}')


class FakeLLMClient:
    def __init__(self, chunks: list[str]) -> None:
        self._chunks = chunks

    def stream_chat_deltas(self, messages, **kwargs):
        yield from self._chunks


@pytest.fixture
def stream_env(monkeypatch):
    """通用桩：LLM key/客户端注入，禁用联网补齐，坐标落地为空操作。"""
    monkeypatch.setattr(settings, "llm_api_key", "test-key")
    monkeypatch.setattr(settings, "llm_generation_web_search", False)

    def _install(chunks: list[str]):
        fake = FakeLLMClient(chunks)
        monkeypatch.setattr("app.agent.trip_stream.get_llm_client", lambda: fake)

    def _no_ground(item, city, cache):
        return None

    monkeypatch.setattr("app.agent.trip_stream._local_ground", _no_ground)
    monkeypatch.setattr("app.agent.trip_stream.fill_suggestion_gaps",
                        lambda rows, city, **kw: rows)
    return _install


def _req(days: int = 3) -> GenerateDayRequest:
    return GenerateDayRequest(city="巴塞罗那", persons=2, days=days, day_no=1,
                              needs_hotel=True, hotel_tier="豪华型")


class TestDailyPlansStreamParser:
    def test_feed_whole_chunk(self):
        parser = DailyPlansStreamParser()
        days = parser.feed(TRIP_JSON)
        assert [d["day_no"] for d in days] == [1, 2, 3]
        final = parser.finish()
        assert final["complete"] is True
        assert final["trip_theme"] == "巴塞罗那·高迪之光"
        assert len(final["suggestions"]) == 2

    def test_feed_char_by_char_matches_whole(self):
        whole = DailyPlansStreamParser()
        whole.feed(TRIP_JSON)
        slow = DailyPlansStreamParser()
        slow_days: list[dict] = []
        for ch in TRIP_JSON:
            slow_days.extend(slow.feed(ch))
        assert slow_days == whole.days
        assert slow.finish() == whole.finish()

    def test_strings_with_braces_and_escapes_do_not_break_scan(self):
        payload = {
            "trip_theme": '花括号}{与"引号"主题',
            "daily_plans": [
                {"day_no": 1, "note": "转义\\\"与{嵌套}",
                 "items": [{"item_type": "attraction", "poi_name": "国泰艺术中心"}]}
            ],
            "suggestions": [],
        }
        parser = DailyPlansStreamParser()
        days = parser.feed(json.dumps(payload, ensure_ascii=False))
        assert len(days) == 1
        assert days[0]["note"] == '转义\\"与{嵌套}'
        assert parser.finish()["trip_theme"] == '花括号}{与"引号"主题'

    def test_truncated_stream_keeps_completed_days(self):
        cut = TRIP_JSON[: TRIP_JSON.index('"day_no":3')]
        parser = DailyPlansStreamParser()
        days = parser.feed(cut)
        assert [d["day_no"] for d in days] == [1, 2]
        final = parser.finish()
        assert final["complete"] is False


class TestDedupPrimitives:
    def test_norm_poi_key_variants(self):
        assert norm_poi_key("圣家堂（Sagrada Família）") == norm_poi_key("圣家堂")
        assert norm_poi_key(" Park Güell ") == norm_poi_key("park Güell")
        assert norm_poi_key("西湖文化广场") != norm_poi_key("西湖")

    def test_haversine_invalid_coords(self):
        assert haversine_m(0, 0, 41.4, 2.17) == float("inf")
        assert haversine_m(None, None, 1, 1) == float("inf")
        assert abs(haversine_m(41.4036, 2.1744, 41.4036, 2.1744)) < 1e-6

    def test_registry_name_and_coord_channels(self):
        reg = PoiSeenRegistry()
        assert not reg.is_duplicate("圣家堂", "attraction")
        reg.register("圣家堂", "attraction", 41.4036, 2.1744)
        # 名称通道
        assert reg.is_duplicate("圣家堂", "attraction")
        # 坐标通道（名称变体）
        assert reg.is_duplicate("圣家堂大教堂", "attraction", 41.40362, 2.17438)
        # 远坐标不同名：不判重（西湖 vs 西湖文化广场场景）
        assert not reg.is_duplicate("西湖文化广场", "attraction", 30.25, 120.16)
        # 酒店豁免：同名合法
        assert not reg.is_duplicate("文华东方酒店巴塞罗那", "hotel")
        reg.register("文华东方酒店巴塞罗那", "hotel", 41.39, 2.16)
        assert not reg.is_duplicate("文华东方酒店巴塞罗那", "hotel", 41.39, 2.16)

    def test_drop_cross_day_duplicates_keeps_first(self):
        plans = [
            {"day_no": 1, "items": [
                {"item_type": "attraction", "poi_name": "圣家堂",
                 "latitude": 41.4036, "longitude": 2.1744}]},
            {"day_no": 2, "items": [
                {"item_type": "attraction", "poi_name": "圣家堂大教堂",
                 "latitude": 41.40362, "longitude": 2.17438},
                {"item_type": "attraction", "poi_name": "古埃尔公园",
                 "latitude": 41.4145, "longitude": 2.1527}]},
            {"day_no": 3, "items": [
                {"item_type": "attraction", "poi_name": "圣家堂（Sagrada Família）",
                 "latitude": 41.4036, "longitude": 2.1744}]},
        ]
        dropped = drop_cross_day_duplicates(plans)
        assert [d["poi_name"] for d in dropped] == ["圣家堂大教堂", "圣家堂（Sagrada Família）"]
        assert [it["poi_name"] for it in plans[1]["items"]] == ["古埃尔公园"]
        assert plans[2]["items"] == []


class TestCityFilter:
    def test_mismatched_city_dropped(self):
        rows = [
            {"poi_name": "米拉之家", "city": "巴塞罗那"},
            {"poi_name": "唐吉诃德涩谷", "city": "东京"},
            {"poi_name": "无城市标注", "city": ""},
        ]
        kept = _filter_suggestions_by_city(rows, "巴塞罗那")
        assert [r["poi_name"] for r in kept] == ["米拉之家", "无城市标注"]

    def test_containment_allows_bilingual_annotation(self):
        rows = [{"poi_name": "米拉之家", "city": "巴塞罗那（Barcelona）"}]
        assert _filter_suggestions_by_city(rows, "Barcelona")


class TestRunGenerateTripStream:
    def test_event_sequence_and_dedup(self, stream_env):
        chunks = [TRIP_JSON[i:i + 64] for i in range(0, len(TRIP_JSON), 64)]
        stream_env(chunks)
        events = list(run_generate_trip_stream(_req()))
        types = [e["type"] for e in events]
        assert types.count("day") == 3
        assert types[-1] == "done"
        done = events[-1]
        assert done["daysExpected"] == 3
        assert done["daysEmitted"] == [1, 2, 3]
        assert done["tripTheme"] == "巴塞罗那·高迪之光"

        # 跨天变体重复（圣家堂大教堂）与名称归一重复都被坐标/名称通道拦截
        day3 = next(e for e in events if e["type"] == "day" and e["plan"]["dayNo"] == 3)
        names = [it["poiName"] for it in day3["plan"]["items"]]
        assert "圣家堂大教堂" not in names
        assert "古埃尔公园" in names

        # 备选池：东京店铺被城市校验丢弃
        suggestions = next(e for e in events if e["type"] == "suggestions")
        names = [s["name"] for s in suggestions["items"]]
        assert "米拉之家" in names
        assert "唐吉诃德涩谷" not in names

    def test_day1_wire_shape_matches_generate_day_contract(self, stream_env):
        stream_env([TRIP_JSON])
        events = list(run_generate_trip_stream(_req()))
        day1 = next(e for e in events if e["type"] == "day")["plan"]
        assert day1["dayNo"] == 1
        item = day1["items"][0]
        assert item["itemType"] == "attraction"
        assert item["poiName"].startswith("圣家堂")
        assert item["startTime"] == "09:00"
        # refs 是模型内部引用编号，不应对外透传
        assert "refs" not in item

    def test_stream_failure_reports_error_for_repair(self, stream_env, monkeypatch):
        stream_env([])

        def _boom():
            raise RuntimeError("upstream down")

        # 覆盖 stream_env 里已安装的 fake：让流式调用直接抛错
        class BoomClient:
            def stream_chat_deltas(self, messages, **kwargs):
                raise RuntimeError("upstream down")
                yield ""  # pragma: no cover - 使其成为生成器

        monkeypatch.setattr("app.agent.trip_stream.get_llm_client", lambda: BoomClient())
        events = list(run_generate_trip_stream(_req()))
        done = events[-1]
        assert done["type"] == "done"
        assert done["daysEmitted"] == []
        assert done["complete"] is False
        assert done["message"]

    def test_missing_llm_key_raises(self, monkeypatch):
        monkeypatch.setattr(settings, "llm_api_key", "")
        with pytest.raises(ValueError):
            list(run_generate_trip_stream(_req()))
