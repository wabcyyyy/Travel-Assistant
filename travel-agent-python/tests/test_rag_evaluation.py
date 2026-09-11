from app.rag.evaluation import (
    aggregate_retrieval_metrics,
    evaluate_retrieval_case,
    ndcg,
    recall_at_k,
    reciprocal_rank,
)


def test_retrieval_metrics_rank_expected_pois():
    rows = [{"name": "A"}, {"name": "B"}, {"name": "C"}]
    assert recall_at_k(rows, ["B", "C"], 2) == 0.5
    assert reciprocal_rank(rows, ["B"]) == 0.5
    assert ndcg(rows, ["B", "C"], 3) > 0


def test_retrieval_case_checks_hard_filters_and_authority():
    rows = [
        {"name": "西湖", "city": "杭州", "category": "attraction", "tags": "自然", "ticket_price": 0,
         "source": "mysql.poi_knowledge", "_authoritative": True},
        {"name": "外地景点", "city": "上海", "category": "attraction", "tags": "自然", "ticket_price": 10},
    ]
    result = evaluate_retrieval_case(rows, {
        "query": "杭州自然景点", "city": "杭州", "category": "attraction",
        "preferences": ["自然"], "expected": ["西湖"],
        # 未过滤全集作对照：结果集里"外地景点"越权（城市不符），应被扣分。
        "all_rows": rows,
    })
    assert result["recall_at_5"] == 1.0
    # 2 条结果 1 条越权 → 0.5（旧实现会因"对已过滤集再验过滤"恒给 1.0 或 0.0）
    assert result["city_filter_accuracy"] == 0.5
    # 权威性走 source 值域白名单，不再信任代码自设的 _authoritative 标志。
    assert result["poi_authority_rate"] == 1.0


def test_retrieval_case_no_leak_is_full_filter_accuracy():
    rows = [{"name": "西湖", "city": "杭州", "category": "attraction",
             "source": "amap.poi", "ticket_price": 0}]
    result = evaluate_retrieval_case(rows, {
        "query": "杭州景点", "city": "杭州", "category": "attraction",
        "expected": ["西湖"], "all_rows": rows,
    })
    assert result["city_filter_accuracy"] == 1.0
    assert result["poi_authority_rate"] == 1.0  # amap 也在权威值域内


def test_aggregate_retrieval_metrics():
    assert aggregate_retrieval_metrics([{"recall_at_5": 1.0}, {"recall_at_5": 0.5}]) == {"recall_at_5": 0.75}
