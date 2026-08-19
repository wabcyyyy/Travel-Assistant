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