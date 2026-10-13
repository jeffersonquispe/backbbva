from __future__ import annotations

from abc import ABC
from dataclasses import dataclass


@dataclass(frozen=True)
class SimilarModusOperandi:
    pattern_id: str
    description: str
    similarity_score: float


class ModusOperandiPort(ABC):
    def find_similar(self, query: str, top_k: int = 5) -> list[SimilarModusOperandi]:
        raise NotImplementedError
