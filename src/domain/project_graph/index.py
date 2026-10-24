from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass

BM25_K1 = 1.4
BM25_B = 0.75

STOPWORDS = frozenset(
    "de la el los las un una unos unas y o en para por con del al se que no su sus es lo "
    "como mas pero me mi te tu si ya hay esta este esto ese esa eso quiero puedo puedes "
    "donde cual cuales cuando hacer tiene tienen the and".split()
)


def tokenize(text: str) -> list[str]:
    folded = unicodedata.normalize("NFKD", text.lower())
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    return [
        _stem(raw)
        for raw in re.findall(r"[a-z0-9]+", folded)
        if raw not in STOPWORDS and len(raw) >= 3
    ]


# Longest first. A light Spanish stemmer: it only has to make "subo", "subir"
# and "subiendo" meet; the graph is small enough that over-stemming is cheap.
_SUFFIXES = (
    "amos", "emos", "imos", "aron", "ieron", "ando", "iendo", "ados", "idos",
    "ado", "ido", "ar", "er", "ir", "an", "en", "as", "es", "os", "o", "a", "e", "s",
)  # fmt: skip
_MIN_STEM = 3


def _stem(token: str) -> str:
    for suffix in _SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= _MIN_STEM:
            return token[: -len(suffix)]
    return token


def camel_split(text: str) -> str:
    return re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)


@dataclass(frozen=True)
class ProjectGraphIndex:
    """BM25 over node name (x3), keywords (x2) and description (x1)."""

    documents: dict[str, list[str]]
    document_frequency: dict[str, int]
    average_length: float

    @classmethod
    def build(
        cls, fields: dict[str, tuple[str, tuple[str, ...], str]]
    ) -> ProjectGraphIndex:
        documents: dict[str, list[str]] = {}
        frequency: dict[str, int] = {}
        for node_id, (name, keywords, description) in fields.items():
            doc = (
                tokenize(camel_split(name)) * 3
                + [tok for word in keywords for tok in tokenize(word)] * 2
                + tokenize(description)
            )
            documents[node_id] = doc
            for token in set(doc):
                frequency[token] = frequency.get(token, 0) + 1
        total_length = sum(len(doc) for doc in documents.values())
        return cls(documents, frequency, total_length / max(len(documents), 1))

    def score(self, weights: dict[str, float]) -> dict[str, float]:
        """BM25 score per node for a weighted bag of query tokens."""
        total = len(self.documents)
        scores: dict[str, float] = {}
        for node_id, doc in self.documents.items():
            if not doc:
                continue
            length_norm = 1 - BM25_B + BM25_B * len(doc) / max(self.average_length, 1)
            score = 0.0
            for token, weight in weights.items():
                tf = doc.count(token)
                if not tf:
                    continue
                df = self.document_frequency.get(token, 0)
                idf = math.log(1 + (total - df + 0.5) / (df + 0.5))
                score += (
                    weight * idf * tf * (BM25_K1 + 1) / (tf + BM25_K1 * length_norm)
                )
            if score > 0:
                scores[node_id] = score
        return scores
