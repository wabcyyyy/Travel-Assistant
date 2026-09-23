"""G0 量测（PLAN-A1 §3）：模型自选点位名的存在性三值分布。

**跑的是上线用的那条判定**（`app/agent/grounding/existence.py`），不是原型：量测与实现
分家会让"测出来的比例"和"跑起来的比例"变成两码事。

方法与结论见 `docs/量测-存在性接地-2026-09-18.md`。做法：对每个城市跑一次
生产 system prompt + **空参考资料池**的单日生成（空池 = 点位全部由模型自选，
正是需要存在性判定的那批；池内名本就来自外部数据），再逐个名字解析：

- VERIFIED    —— 解析器给出同一实体且在目的地范围内（可背书）
- NOT_FOUND   —— provider 成功应答且明确回了"没有"
- UNKNOWN     —— 没问到 / 名字对不上门槛 / 预算耗尽
- OUT_OF_AREA —— 解析成功但落在别的城市/国家（09-19 复评里唯一随时有效的删除信号）

用法（需要 LLM / OTM / Nominatim 三个外部服务可达；无 DB）：
    uv run python scripts/probe_grounding_coverage.py
    uv run python scripts/probe_grounding_coverage.py --cities 杭州,北京
产物：--out 的 JSON（逐市增量落盘，中断可续）。控制台只打 ASCII（Windows GBK
码页会因中文抛 UnicodeEncodeError，那会让"报告结果"这件事本身把脚本炸掉）。
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent.core.json_utils import parse_llm_json_or_none
from app.agent.generation.content.day_prompts import GENERATION_TEMPERATURE
from app.agent.generation.rules.generation_core import day_hotel_clause
from app.agent.grounding import existence
from app.common.config import settings
from app.common.llm_client import get_llm_client
from app.prompts.open_generation import open_day_system_prompt

# (城市, OTM 定位用英文名, 是否国内)——国内/海外分开统计：两家数据源的覆盖
# 差异极大（实测国内 NOT_FOUND 49.6% vs 海外 14.9%），混在一起的比例没法用。
CITIES: list[tuple[str, str, bool]] = [
    ("杭州", "Hangzhou", True),
    ("北京", "Beijing", True),
    ("成都", "Chengdu", True),
    ("西安", "Xian", True),
    ("东京", "Tokyo", False),
    ("巴黎", "Paris", False),
]

VERIFIED = "VERIFIED"
NOT_FOUND = "NOT_FOUND"
UNKNOWN = "UNKNOWN"
OUT_OF_AREA = "OUT_OF_AREA"
STATES = (VERIFIED, NOT_FOUND, UNKNOWN, OUT_OF_AREA)


class _NoMemory:
    """open_day_system_prompt 只需要 mem.as_sorted_list()。"""

    def as_sorted_list(self) -> list[str]:
        return []


# 与 day_stream.llm_open_day 同文：量测要的是生产分布
_PACE = (
    "根据用户偏好、景点游玩时长与地理距离自主决定当日节奏："
    "城市观光/美食/打卡类偏好可安排 3-5 个景点与 2-3 餐，"
    "自然风光/慢节奏/长途跨区可 2-3 个景点并留足休息；"
    "相邻点位间预留合理交通时间，禁止为凑数堆砌远距离点位。"
    "餐饮时段：午餐排在 11:00-13:30，晚餐排在 17:30-20:30，"
    "禁止一天安排两顿午餐；正餐优先一午一晚。"
)


def _names_from_plan(plan: dict[str, Any]) -> list[dict[str, str]]:
    """一次单日产出里的全部待判名字：items（不含 transport）+ suggestions。"""
    out: list[dict[str, str]] = []
    for item in plan.get("items") or []:
        if not isinstance(item, dict) or item.get("item_type") == "transport":
            continue
        name = str(item.get("poi_name") or "").strip()
        if name:
            out.append({"name": name, "where": "item", "category": str(item.get("item_type") or "attraction")})
    for sug in plan.get("suggestions") or []:
        if not isinstance(sug, dict):
            continue
        name = str(sug.get("poi_name") or "").strip()
        if name:
            out.append({"name": name, "where": "suggestion", "category": str(sug.get("category") or "attraction")})
    return out


def _names_from_raw(raw: str) -> list[dict[str, str]]:
    """JSON 被截断时的名字兜底提取（生产口径会整篇解析失败，见量测报告 §5）。

    按 `"suggestions"` 标记切分前半/后半：两段的判定通路完全相同，只是分组
    统计需要区分它们。
    """
    marker = raw.find('"suggestions"')
    head, tail = (raw, "") if marker < 0 else (raw[:marker], raw[marker:])
    out: list[dict[str, str]] = []
    for where, chunk in (("item", head), ("suggestion", tail)):
        for name in re.findall(r'"poi_name"\s*:\s*"([^"]{1,40})"', chunk):
            if name.strip():
                out.append({"name": name.strip(), "where": where, "category": "attraction"})
    return out


def _verdict(name: str, city: str) -> dict[str, Any]:
    """单个名字走 shipped 判定，映射到报告用的四档。"""
    started = time.perf_counter()
    result = existence.resolve_poi(name, city)
    elapsed = round((time.perf_counter() - started) * 1000)
    if result.grounded:
        state = VERIFIED
    elif result.out_of_area:
        state = OUT_OF_AREA
    elif result.state == existence.NOT_FOUND:
        state = NOT_FOUND
    else:
        state = UNKNOWN
    return {
        "verdict": state,
        "provider": result.provider,
        "reason": result.reason,
        "resolve_ms": elapsed,
        "resolved_name": result.name,
    }


def probe_city(city_cn: str, city_en: str, domestic: bool, llm_model: str | None) -> dict[str, Any]:
    """单个城市：生成一天草案 → 每个唯一名字走 shipped 判定。"""
    existence.reset_existence_state()  # 判定与城市中心记忆都不许跨城串用
    system = open_day_system_prompt(
        day_no=1, pace=_PACE, hotel_clause=day_hotel_clause(True), hotel_hint="", mem=_NoMemory()
    )
    started_llm = time.perf_counter()
    try:
        raw = get_llm_client().complete(
            f"目的地：{city_cn}（第 1 天，2 人）",
            system_prompt=system,
            temperature=GENERATION_TEMPERATURE,
            # 与生产同一预算：3200 实测装不下这个输出契约（量测报告 §5）
            max_tokens=8000,
            model=llm_model,
            json_mode=True,
        )
    except Exception as exc:
        return {"city": city_cn, "error": f"llm:{type(exc).__name__}:{str(exc)[:120]}", "rows": []}
    llm_ms = round((time.perf_counter() - started_llm) * 1000)
    plan = parse_llm_json_or_none(raw) or {}
    names = _names_from_plan(plan) or _names_from_raw(raw or "")

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in names:
        name = entry["name"]
        if name in seen:
            continue
        seen.add(name)
        rows.append({**entry, **_verdict(name, city_cn), "domestic": domestic})

    return {
        "city": city_cn,
        "city_en": city_en,
        "domestic": domestic,
        "llm_ms": llm_ms,
        "llm_model": llm_model or settings.llm_model,
        "json_parsed": bool(plan),
        "item_names": [r["name"] for r in rows if r["where"] == "item"],
        "rows": rows,
    }


def _stat(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = dict.fromkeys(STATES, 0)
    reasons: dict[str, int] = {}
    latencies: list[int] = []
    for row in rows:
        verdict = str(row["verdict"])
        counts[verdict] = counts.get(verdict, 0) + 1
        if verdict in (UNKNOWN, OUT_OF_AREA):
            key = f"{verdict}:{row.get('reason') or 'unknown'}"
            reasons[key] = reasons.get(key, 0) + 1
        latencies.append(int(row.get("resolve_ms") or 0))
    decidable = counts[VERIFIED] + counts[NOT_FOUND] + counts[UNKNOWN]
    latencies.sort()
    rates = {}
    for key, value in counts.items():
        base = len(rows) if key == OUT_OF_AREA else decidable
        rates[key] = round(value / base, 4) if base else 0.0
    return {
        "total": len(rows),
        "decidable": decidable,
        "counts": counts,
        "rates": rates,
        "unknown_reasons": reasons,
        "latency_ms": {
            "p50": latencies[len(latencies) // 2] if latencies else 0,
            "p95": latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))] if latencies else 0,
            "max": latencies[-1] if latencies else 0,
        },
    }


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    """三值比例（总体 / 国内 / 海外 / items vs suggestions）。"""
    all_rows = [r for res in results for r in res.get("rows") or []]
    per_run = [len(res.get("rows") or []) for res in results if res.get("rows")]
    return {
        "overall": _stat(all_rows),
        "domestic": _stat([r for r in all_rows if r["domestic"]]),
        "overseas": _stat([r for r in all_rows if not r["domestic"]]),
        "items_only": _stat([r for r in all_rows if r["where"] == "item"]),
        "suggestions_only": _stat([r for r in all_rows if r["where"] == "suggestion"]),
        "per_run_names_median": statistics.median(per_run or [0]),
    }


def _ascii(text: str) -> str:
    return text.encode("ascii", "backslashreplace").decode("ascii")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cities", default=",".join(c[0] for c in CITIES))
    parser.add_argument("--out", default="docs/probe-grounding.json")
    parser.add_argument("--model", default=None)
    args = parser.parse_args()

    wanted = {c.strip() for c in str(args.cities).split(",") if c.strip()}
    targets = [c for c in CITIES if c[0] in wanted]
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    for city_cn, city_en, domestic in targets:
        print(_ascii(f"[probe] city={city_cn} start"), flush=True)
        result = probe_city(city_cn, city_en, domestic, args.model)
        counts: dict[str, int] = dict.fromkeys(STATES, 0)
        for row in result.get("rows") or []:
            counts[str(row["verdict"])] += 1
        print(
            _ascii(
                f"[probe] city={city_cn} names={len(result.get('rows') or [])} "
                + " ".join(f"{key[0]}={counts[key]}" for key in STATES)
                + f" err={result.get('error', '')}"
            ),
            flush=True,
        )
        results.append(result)
        out_path.write_text(
            json.dumps({"results": results, "summary": summarize(results)}, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )

    print(_ascii(json.dumps(summarize(results), ensure_ascii=False)), flush=True)
    print(_ascii(f"[probe] written {out_path}"), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
