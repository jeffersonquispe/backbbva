from __future__ import annotations

from abc import ABC
from dataclasses import dataclass


@dataclass(frozen=True)
class SimilarFraudCase:
    case_id: str
    summary: str
    outcome: str
    similarity_score: float


class SimilarFraudCasePort(ABC):
    def find_similar(self, query: str, top_k: int = 5) -> list[SimilarFraudCase]:
        raise NotImplementedError
