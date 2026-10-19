from __future__ import annotations

from abc import ABC, abstractmethod

from src.application.ports.embedding_port import EmbeddingUnitOfWork
from src.application.ports.monitoring_port import MonitoringPort


class EmbeddingUnitOfWorkFactory(ABC):
    @abstractmethod
    def create(
        self,
        *,
        model: str,
        monitoring: MonitoringPort,
        operation_name: str,
    ) -> EmbeddingUnitOfWork: ...
