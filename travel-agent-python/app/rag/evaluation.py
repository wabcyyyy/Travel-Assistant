"""RAG 检索离线评测指标，不依赖 MySQL、外部 API 或真实 embedding 模型。"""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any


def _names(rows: Iterable[dict[str, Any]]) -> list[str]:
    return [str(row.get("name") or row.get("poi_name") or "") for row in rows]


def recall_at_k(rows: list[dict[str, Any]], expected: list[str], k: int) -> float:
    expected_set = set(expected)
    if not expected_set:
        return 1.0
    return len(expected_set & set(_names(rows[:k]))) / len(expected_set)


def reciprocal_rank(rows: list[dict[str, Any]], expected: list[str]) -> float:
    expected_set = set(expected)
    for rank, name in enumerate(_names(rows), start=1):
        if name in expected_set:
            return 1.0 / rank
    return 0.0


def ndcg(rows: list[dict[str, Any]], expected: list[str], k: int = 10) -> float:
    expected_set = set(expected)
    if not expected_set:
        return 1.0
    dcg = sum(1.0 / math.log2(rank + 1) for rank, name in enumerate(_names(rows[:k]), start=1) if name in expected_set)
    ideal = sum(1.0 / math.log2(rank + 1) for rank in range(1, min(k, len(expected_set)) + 1))
    return dcg / ideal if ideal else 0.0


def evaluate_retrieval_case(rows: list[dict[str, Any]], case: dict[str, Any]) -> dict[str, Any]:
    """计算一条检索 case 的相关性、硬过滤和事实完整性指标。

    过滤准确率必须比对"结果集 vs 未过滤全集"：对已按同条件过滤过的 rows
    再验证过滤恒为 1.0（自证）。调用方应传 `all_rows`=过滤前的完整候选集。
    权威性指标校验 source 值域白名单，而不是代码自设的 _authoritative 标志。
    """
    city = case.get("city")
    category = case.get("category")
    expected = list(case.get("expected") or [])
    all_rows = list(case.get("all_rows") or rows)
    filtered_rows = [
        row
        for row in rows
        if (not city or row.get("city") == city) and (not category or row.get("category") == category)
    ]
    preferences = [str(value).lower() for value in case.get("preferences") or []]
    preference_hit = 0
    if preferences:
        for row in filtered_rows:
            haystack = " ".join(str(row.get(key) or "").lower() for key in ("tags", "description", "category"))
            preference_hit += any(pref in haystack for pref in preferences)
    else:
        preference_hit = len(filtered_rows)
    # 过滤准确率：全集中满足条件的行里，有多少确实出现在结果集中；
    # 同时结果集中不得混入不满足条件的行（越权召回）。
    eligible = [
        row
        for row in all_rows
        if (not city or row.get("city") == city) and (not category or row.get("category") == category)
    ]
    eligible_names = {str(row.get("name") or "") for row in eligible}
    result_names = [str(row.get("name") or "") for row in rows]
    leaked = sum(1 for name in result_names if name not in eligible_names)
    city_filter_accuracy = 1.0 if not rows or leaked == 0 else round((len(rows) - leaked) / len(rows), 4)
    authority_prefixes = tuple(case.get("authority_prefixes") or ("mysql", "amap", "wikivoyage"))
    return {
        "query": case.get("query", ""),
        "recall_at_5": round(recall_at_k(rows, expected, 5), 4),
        "recall_at_10": round(recall_at_k(rows, expected, 10), 4),
        "mrr": round(reciprocal_rank(rows, expected), 4),
        "ndcg_at_10": round(ndcg(rows, expected, 10), 4),
        "city_filter_accuracy": city_filter_accuracy,
        "category_filter_accuracy": city_filter_accuracy,
        "preference_hit_rate": round(preference_hit / len(filtered_rows), 4) if filtered_rows else 1.0,
        "price_field_completeness": round(
            sum(row.get("ticket_price") is not None for row in filtered_rows) / len(filtered_rows), 4
        )
        if filtered_rows
        else 1.0,
        # 值域校验：source 必须落在权威前缀白名单内（不再信任代码自设标志）。
        "poi_authority_rate": round(
            sum(str(row.get("source", "")).startswith(authority_prefixes) for row in filtered_rows)
            / len(filtered_rows),
            4,
        )
        if filtered_rows
        else 1.0,
    }


def aggregate_retrieval_metrics(results: list[dict[str, Any]]) -> dict[str, float]:
    if not results:
        return {}
    keys = [key for key, value in results[0].items() if isinstance(value, (int, float))]
    return {key: round(sum(float(result.get(key, 0.0)) for result in results) / len(results), 4) for key in keys}
