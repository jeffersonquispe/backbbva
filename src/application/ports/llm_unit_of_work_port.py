from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum

from src.application.ports.monitoring_port import MonitoringPort


class LLMMessageRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


@dataclass(frozen=True)
class LLMMessage:
    role: LLMMessageRole
    content: str


@dataclass(frozen=True)
class LLMInvocationResult:
    content: str
    model: str
    finish_reason: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


class LLMUnitOfWork(ABC):
    """Wraps one logical LLM operation (e.g. "write_email", "review_email").

    Every invocation is instrumented through the monitoring instance it was
    built with, so step use cases never talk to the monitoring port
    directly.
    """

    @abstractmethod
    def invoke(self, messages: list[LLMMessage]) -> LLMInvocationResult: ...


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
