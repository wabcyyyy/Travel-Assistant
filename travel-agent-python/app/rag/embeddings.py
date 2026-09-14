"""轻量级本地向量化（无外部模型依赖）。

职责：
- 为中文/英文文本提供确定性的稠密向量表示，供 RAG 检索使用。

实现要点：
- 采用 "字符/词 n-gram + 哈希桶" 方案：中文按单字、英文数字按词切分，
  再取相邻二元组，用 zlib.crc32 映射到固定维度并对向量做 L2 归一化；
- HashedNGramEmbedding 暴露与 sentence-transformers 兼容的 __call__/name 接口，
  便于在不引入重模型时仍能跑通向量检索。

依赖：
- numpy；无外部服务依赖（纯算法）。
"""

import re
import zlib

import numpy as np

_DIM = 256
_WORD_RE = re.compile(r"[\u4e00-\u9fff]|[a-zA-Z0-9]+")


def _ngrams(text: str) -> list[str]:
    tokens = _WORD_RE.findall(text.lower())
    grams: list[str] = []
    for token in tokens:
        if len(token) <= 2:
            grams.append(token)
        for i in range(len(token) - 1):
            grams.append(token[i : i + 2])
    return grams


def embed(text: str, dim: int = _DIM) -> list[float]:
    vec = np.zeros(dim, dtype=np.float32)
    for gram in _ngrams(text):
        idx = zlib.crc32(gram.encode("utf-8")) % dim
        vec[idx] += 1.0
    norm = float(np.linalg.norm(vec))
    if norm > 0:
        vec = vec / norm
    return vec.tolist()


class HashedNGramEmbedding:
    def __init__(self, dim: int = _DIM) -> None:
        self.dim = dim

    def __call__(self, input: list[str]) -> list[list[float]]:
        return [embed(doc, self.dim) for doc in input]

    def name(self) -> str:
        return "hashed-ngram-" + str(self.dim)
