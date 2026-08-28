from __future__ import annotations

from src.application.ports.analyst_capacity_import_port import (
    AnalystCapacityImportDispatcher,
)
from src.infrastructure.entrypoint.worker.celery.tasks import (
    parse_analyst_capacity_workbook_task,
)


class CeleryAnalystCapacityImportDispatcher(AnalystCapacityImportDispatcher):
    def dispatch(self, content_b64: str) -> str:
        result = parse_analyst_capacity_workbook_task.delay(content_b64)
        return result.id
