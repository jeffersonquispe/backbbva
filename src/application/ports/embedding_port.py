from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class EmbeddingResult:
    vectors: list[list[float]]
    model: str
    dimensions: int


class EmbeddingUnitOfWork(ABC):
    """Wraps one logical embedding operation (e.g. "fraud_knowledge_ingest").

    Every invocation is instrumented through the monitoring instance it was
    built with, so callers never talk to the monitoring port directly.
    """

    @abstractmethod
    def embed(self, texts: list[str]) -> EmbeddingResult: ...
