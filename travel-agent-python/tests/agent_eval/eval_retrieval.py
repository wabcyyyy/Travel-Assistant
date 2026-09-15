"""离线 RAG 检索评测入口（固定 fixture，不访问 MySQL/外部模型）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.rag.evaluation import aggregate_retrieval_metrics, evaluate_retrieval_case
from app.rag.retriever import (
    HashedEmbeddingProvider,
    HybridRetriever,
    NoopReranker,
    build_poi_document,
)
from tests.agent_eval.mock_llm import catalog


class FixtureCollection:
    def __init__(self, provider, documents):
        self.provider = provider
        self.documents = documents

    def query(self, *, vector, limit, where=None):
        rows = []
        for item in self.documents.values():
            if any(item["metadata"].get(key) != value for key, value in (where or {}).items()):
                continue
            doc_vector = self.provider.embed_query(item["document"])
            similarity = sum(a * b for a, b in zip(vector, doc_vector, strict=False))
            rows.append((similarity, item["metadata"]))
        rows.sort(key=lambda value: value[0], reverse=True)
        return [(meta, score) for score, meta in rows[:limit]]


def run_case(case: dict, provider=None) -> dict:
    fixture = catalog(case["city"])
    source_records = fixture["attractions"] if case["category"] == "attraction" else fixture["foods"]
    # 旧 Agent fixture 为生成评测服务，省略了 city；检索 fixture 在评测时补齐
    # 该权威字段，以真实执行 where city/category 硬过滤。
    records = [dict(row, city=case["city"], source="mysql.poi_knowledge") for row in source_records]
    provider = provider or HashedEmbeddingProvider()
    documents = {str(row["id"]): {"document": build_poi_document(row), "metadata": row} for row in records}
    # 离线 fixture 评测固定不启用精排，保持基线可复现。
    retriever = HybridRetriever(FixtureCollection(provider, documents), provider, reranker=NoopReranker())
    retriever.set_documents(documents)
    rows = retriever.search(
        case["query"], city=case["city"], category=case["category"], top_k=10, preferences=case.get("preferences")
    )
    # 过滤准确率必须有"未过滤全集"作对照，否则对已过滤结果再验过滤恒为 1.0。
    case_with_universe = dict(case, all_rows=records)
    return evaluate_retrieval_case(rows, case_with_universe)


def _resolve_provider(name: str):
    """hashed = 零依赖基线；semantic = 本地语义模型（需先 fetch_rag_model.py 预置）。"""
    if name == "hashed":
        return HashedEmbeddingProvider()
    from app.rag.retriever import create_embedding_provider

    provider = create_embedding_provider("semantic")
    if getattr(provider, "fallback", False):
        raise SystemExit("语义 provider 降级为 hashed：请先执行 scripts/fetch_rag_model.py 预置模型")
    return provider


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="离线 RAG 检索评测（fixture）")
    parser.add_argument(
        "--provider",
        default="hashed",
        choices=["hashed", "semantic"],
        help="hashed=零依赖基线；semantic=本地 bge 语义（需预置模型）",
    )
    args = parser.parse_args()
    provider = _resolve_provider(args.provider)
    cases = json.loads((Path(__file__).with_name("retrieval_cases.json")).read_text(encoding="utf-8"))
    results = [run_case(case, provider) for case in cases]
    print(
        json.dumps(
            {
                "mode": f"offline-fixture-{provider.provider_name}",
                "case_count": len(results),
                "metrics": aggregate_retrieval_metrics(results),
                "details": results,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
