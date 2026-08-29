"""离线 RAG 检索评测入口（固定 fixture，不访问 MySQL/外部模型）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.rag.evaluation import aggregate_retrieval_metrics, evaluate_retrieval_case
from app.rag.retriever import HashedEmbeddingProvider, HybridRetriever, build_poi_document
from tests.agent_eval.mock_llm import catalog


class FixtureCollection:
    def __init__(self, provider, documents):
        self.provider = provider
        self.documents = documents

    def query(self, *, query_embeddings, n_results, where, include):
        conditions = where.get("$and", []) if where and "$and" in where else ([where] if where else [])
        rows = []
        for item in self.documents.values():
            if any(item["metadata"].get(next(iter(condition))) != next(iter(condition.values()))
                   for condition in conditions):
                continue
            vector = self.provider.embed_query(item["document"])
            similarity = sum(a * b for a, b in zip(query_embeddings[0], vector))
            rows.append((similarity, item["metadata"]))
        rows.sort(key=lambda value: value[0], reverse=True)
        return {"metadatas": [[row[1] for row in rows[:n_results]]],
                "distances": [[1 - row[0] for row in rows[:n_results]]]}


def run_case(case: dict) -> dict:
    fixture = catalog(case["city"])
    source_records = fixture["attractions"] if case["category"] == "attraction" else fixture["foods"]
    # 旧 Agent fixture 为生成评测服务，省略了 city；检索 fixture 在评测时补齐
    # 该权威字段，以真实执行 where city/category 硬过滤。
    records = [dict(row, city=case["city"], source="mysql.poi_knowledge") for row in source_records]
    provider = HashedEmbeddingProvider()
    documents = {str(row["id"]): {"document": build_poi_document(row), "metadata": row} for row in records}
    retriever = HybridRetriever(FixtureCollection(provider, documents), provider)
    retriever.set_documents(documents)
    rows = retriever.search(case["query"], city=case["city"], category=case["category"], top_k=10,
                            preferences=case.get("preferences"))
    return evaluate_retrieval_case(rows, case)


def main() -> int:
    cases = json.loads((Path(__file__).with_name("retrieval_cases.json")).read_text(encoding="utf-8"))
    results = [run_case(case) for case in cases]
    print(json.dumps({"mode": "offline-fixture-hashed", "case_count": len(results),
                      "metrics": aggregate_retrieval_metrics(results), "details": results},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
