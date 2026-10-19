from __future__ import annotations

from src.application.ports.analyst_capacity_import_port import (
    AnalystCapacityImportResult,
)
from src.application.ports.analyst_capacity_import_status_reader_port import (
    AnalystCapacityImportStatusReader,
)


class GetAnalystCapacityImportUseCase:
    def __init__(self, reader: AnalystCapacityImportStatusReader) -> None:
        self._reader = reader

    def execute(self, task_id: str) -> AnalystCapacityImportResult:
        return self._reader.read(task_id)
