from __future__ import annotations

from src.application.ports.analyst_capacity_import_port import (
    AnalystCapacityImportDispatcher,
)
from src.infrastructure.queues.celery.app import app

_TASK_NAME = "analyst_capacity.parse_workbook"


class CeleryAnalystCapacityImportDispatcher(AnalystCapacityImportDispatcher):
    def dispatch(self, content_b64: str) -> str:
        result = app.send_task(_TASK_NAME, args=[content_b64])
        return result.id
