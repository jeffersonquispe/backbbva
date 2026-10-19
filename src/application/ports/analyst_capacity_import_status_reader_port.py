from __future__ import annotations

from abc import ABC

from src.application.ports.analyst_capacity_import_port import (
    AnalystCapacityImportResult,
)


class AnalystCapacityImportStatusReader(ABC):
    """Reads back a dispatched import's status/result by task id. Adapter:
    infrastructure/queues/celery/analyst_capacity_import_status_reader.py.
    """

    def read(self, task_id: str) -> AnalystCapacityImportResult:
        raise NotImplementedError
