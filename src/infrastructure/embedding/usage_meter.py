from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from src.application.ports.embedding_port import EmbeddingResult, EmbeddingUnitOfWork
from src.application.ports.embedding_unit_of_work_factory_port import (
    EmbeddingUnitOfWorkFactory,
)
from src.application.ports.monitoring_port import MonitoringPort


@dataclass
class EmbeddingUsage:
    """Embedding work done while a measurement was open. The provider does not
    return token counts through LangChain, so characters are the size proxy."""

    calls: int = 0
    texts: int = 0
    characters: int = 0

    def as_metrics(self) -> dict[str, int]:
        """Safe metrics for a specialist; empty when nothing was embedded."""
        if not self.calls:
            return {}
        return {
            "embedding_calls": self.calls,
            "embedding_texts": self.texts,
            "embedding_characters": self.characters,
        }


_current: ContextVar[EmbeddingUsage | None] = ContextVar(
    "embedding_usage", default=None
)


@contextmanager
def measure_embedding_usage() -> Iterator[EmbeddingUsage]:
    """Collect every metered embedding call made in this context (thread or
    task), so concurrent executions never mix their counts."""
    usage = EmbeddingUsage()
    token = _current.set(usage)
    try:
        yield usage
    finally:
        _current.reset(token)


class MeteredEmbeddingUnitOfWork(EmbeddingUnitOfWork):
    def __init__(self, inner: EmbeddingUnitOfWork) -> None:
        self._inner = inner

    def embed(self, texts: list[str]) -> EmbeddingResult:
        result = self._inner.embed(texts)
        usage = _current.get()
        if usage is not None:
            usage.calls += 1
            usage.texts += len(texts)
            usage.characters += sum(len(text) for text in texts)
        return result


class MeteredEmbeddingUnitOfWorkFactory(EmbeddingUnitOfWorkFactory):
    """Decorates any embedding backend; counting only happens inside
    ``measure_embedding_usage``, so other callers pay nothing extra."""

    def __init__(self, inner: EmbeddingUnitOfWorkFactory) -> None:
        self._inner = inner

    def create(
        self,
        *,
        model: str,
        monitoring: MonitoringPort,
        operation_name: str,
    ) -> EmbeddingUnitOfWork:
        return MeteredEmbeddingUnitOfWork(
            self._inner.create(
                model=model, monitoring=monitoring, operation_name=operation_name
            )
        )
