from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SimilarFraudTaxonomy:
    code: str
    name: str
    description: str
    similarity_score: float


class FraudTaxonomyPort:
    def find_similar(self, query: str, top_k: int = 5) -> list[SimilarFraudTaxonomy]:
        raise NotImplementedError
