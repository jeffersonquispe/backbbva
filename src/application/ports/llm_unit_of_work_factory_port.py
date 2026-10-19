from __future__ import annotations

from abc import ABC, abstractmethod

from src.application.ports.llm_unit_of_work_port import LLMUnitOfWork
from src.application.ports.monitoring_port import MonitoringPort


class LLMUnitOfWorkFactory(ABC):
    @abstractmethod
    def create(
        self,
        *,
        model: str,
        monitoring: MonitoringPort,
        operation_name: str,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> LLMUnitOfWork: ...
