from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Any


class MonitoringStatus(StrEnum):
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class MonitoringSpan(ABC):
    """One tracked operation instance.

    Start time and execution time are handled by the implementation
    (recorded on creation and on `finish`); callers only report the
    operation-specific facts.
    """

    @abstractmethod
    def write_input(self, data: dict[str, Any]) -> None: ...

    @abstractmethod
    def write_result(self, data: dict[str, Any]) -> None: ...

    @abstractmethod
    def write_inner_logs(
        self, entries: dict[str, Any] | list[dict[str, Any]]
    ) -> None: ...

    @abstractmethod
    def write_operation_metas(self, metadata: dict[str, Any]) -> None: ...

    @abstractmethod
    def record_dependency(
        self,
        name: str,
        kind: str,
        metadata: dict[str, Any] | None = None,
    ) -> None: ...

    @abstractmethod
    def finish(self, error: str | None = None) -> None: ...

    def __enter__(self) -> "MonitoringSpan":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.finish(str(exc) if exc is not None else None)


class MonitoringPort(ABC):
    @abstractmethod
    def start(
        self,
        operation_name: str,
        operation_type: str,
        metadata: dict[str, Any] | None = None,
    ) -> MonitoringSpan: ...
