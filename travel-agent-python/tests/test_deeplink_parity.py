"""深链语义 parity（Y4）：用 tests/golden/deeplink_cases.json 钉住后端地图深链口径。

前后端各有一份深链实现（本模块测 app.agent.places；前端 src/utils/geo.ts 由
travel-frontend-vue/src/utils/deeplink.parity.test.ts 读**同一份 case 文件**断言）。
任何一侧单方面改语义都会让对侧或本侧显形。断言粒度 = 协议 host + path 前缀 +
关键查询参数存在/缺席——src/callnative/policy/coordinate 与坐标数值（GCJ-02
换算等）属实现细节，不做整串相等。两侧已确认的口径差异逐条见
tests/golden/deeplink_parity.md 差异表；下表 DIFF_NOTES 是其在断言层的落点。
"""

from __future__ import annotations

import json
import pathlib
from urllib.parse import parse_qs, urlsplit

import pytest

from app.agent.places import map_directions_url, map_search_url

CASES_PATH = pathlib.Path(__file__).parent / "golden" / "deeplink_cases.json"

#: 与 deeplink_parity.md 差异表一一对应：两侧期望不同的 case 必须在此登记，
#: 值只写一句结论 + 编号，细节以差异表为准。
DIFF_NOTES = {
    "search_domestic_with_coords": "D1 待统一：有坐标时后端 marker 打点、前端关键词搜索。",
    "search_zero_sentinel": "D7 待统一：0/0 哨兵后端误判海外走谷歌、前端当无坐标。",
    "search_out_of_range_coords": "D2 待统一：越界坐标后端误判海外走谷歌、前端回落关键词。",
    "search_hanzi_foreign_city_no_coords": "D3 待统一：汉字名海外城市（巴厘岛）两侧判定相反。",
    "search_foreign_with_coords": "D4 已知且接受：query 取坐标还是名称，低于断言粒度。",
    "route_domestic_four_stops": "D5 待统一：高德 via 后端无上限、前端限 1 超出返回空。",
    "route_foreign_seven_stops": "D6 已知且接受：谷歌 waypoints 后端无上限、前端限 3。",
    "route_out_of_range_stop": "D2 同源：越界点后端纳入路线、前端剔除。",
}


def _cases() -> list[dict]:
    return json.loads(CASES_PATH.read_text(encoding="utf-8"))["cases"]


def _assert_protocol(url: str | None, expect: dict, note: str = "") -> None:
    suffix = f"（{note}）" if note else ""
    if expect.get("null"):
        assert url is None, f"应返回空{suffix}"
        return
    assert url is not None, f"应产出链接{suffix}"
    parts = urlsplit(url)
    assert parts.hostname == expect["host"], f"{url}{suffix}"
    assert parts.path.startswith(expect["path"]), f"{url}{suffix}"
    query = parse_qs(parts.query)
    for key in expect.get("params", []):
        assert query.get(key), f"missing {key!r}: {url}{suffix}"
    for key in expect.get("absent_params", []):
        assert key not in query, f"unexpected {key!r}: {url}{suffix}"


@pytest.mark.parametrize("case", _cases(), ids=lambda c: c["name"])
def test_deeplink_backend_protocol(case):
    """后端 places 深链按 golden case 钉协议口径；两侧差异点见 DIFF_NOTES 与差异表。"""
    expect = case["backend"]
    stops = case["input"].get("stops")
    if stops is not None:
        url = map_directions_url([dict(stop) for stop in stops])
    else:
        url = map_search_url(
            case["input"]["name"],
            case["input"]["city"],
            latitude=case["input"].get("latitude"),
            longitude=case["input"].get("longitude"),
        )
    _assert_protocol(url, expect, DIFF_NOTES.get(case["name"], ""))
