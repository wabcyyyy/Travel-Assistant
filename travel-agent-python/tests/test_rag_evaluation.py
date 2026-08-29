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
    })
    assert result["recall_at_5"] == 1.0
    assert result["city_filter_accuracy"] == 0.0
    assert result["poi_authority_rate"] == 1.0


def test_aggregate_retrieval_metrics():
    assert aggregate_retrieval_metrics([{"recall_at_5": 1.0}, {"recall_at_5": 0.5}]) == {"recall_at_5": 0.75}
