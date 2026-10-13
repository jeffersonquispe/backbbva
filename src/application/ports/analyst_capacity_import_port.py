from __future__ import annotations

from abc import ABC
from dataclasses import dataclass, field
from enum import StrEnum

from src.application.ports.configuration_port import DayProfile


class AnalystCapacityImportStatus(StrEnum):
    PENDING = "PENDING"
    READY = "READY"
    FAILED = "FAILED"


@dataclass
class AnalystCapacityImportResult:
    status: AnalystCapacityImportStatus
    profiles: list[DayProfile] = field(default_factory=list)
    day_overrides: dict[int, str] = field(default_factory=dict)
    error: str | None = None


class AnalystCapacityImportDispatcher(ABC):
    """Kicks off async parsing of an uploaded analyst-capacity workbook.
    Unlike datasets (dataset_analysis_port.py's DatasetAnalysisDispatcher +
    a DynamoDB summary table for polling), this import is small and
    one-shot - its result only ever needs to reach the frontend draft once,
    never re-listed or persisted - so there's no repository here. Celery's
    own result backend (already configured, see CELERY_RESULT_BACKEND) is
    the polling store; see AnalystCapacityImportStatusReader. Adapter:
    infrastructure/queues/celery/analyst_capacity_import_dispatcher.py.
    Task: infrastructure/entrypoint/worker/celery/tasks.py's
    parse_analyst_capacity_workbook_task.
    """

    def dispatch(self, content_b64: str) -> str:
        """Returns the Celery task id to poll via AnalystCapacityImportStatusReader."""
        raise NotImplementedError


class AnalystCapacityImportStatusReader(ABC):
    """Reads back a dispatched import's status/result by task id. Adapter:
    infrastructure/queues/celery/analyst_capacity_import_status_reader.py.
    """

    def read(self, task_id: str) -> AnalystCapacityImportResult:
        raise NotImplementedError
