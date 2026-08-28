from __future__ import annotations

from celery.result import AsyncResult
from celery import states

from src.application.ports.analyst_capacity_import_port import (
    AnalystCapacityImportResult,
    AnalystCapacityImportStatus,
    AnalystCapacityImportStatusReader,
)
from src.application.ports.configuration_port import DayProfile
from src.infrastructure.entrypoint.worker.celery.celery_app import app

_PENDING_STATES = {states.PENDING, states.RECEIVED, states.STARTED, states.RETRY}


class CeleryAnalystCapacityImportStatusReader(AnalystCapacityImportStatusReader):
    def read(self, task_id: str) -> AnalystCapacityImportResult:
        result = AsyncResult(task_id, app=app)

        if result.state in _PENDING_STATES:
            return AnalystCapacityImportResult(status=AnalystCapacityImportStatus.PENDING)

        if result.state == states.SUCCESS:
            payload = result.result
            profiles = [DayProfile(**p) for p in payload["profiles"]]
            day_overrides = {
                int(day): profile_id for day, profile_id in payload["day_overrides"].items()
            }
            return AnalystCapacityImportResult(
                status=AnalystCapacityImportStatus.READY,
                profiles=profiles,
                day_overrides=day_overrides,
            )

        # FAILURE / REVOKED / anything else - report as failed rather than
        # raising, so a bad task id degrades to a clear "FAILED" instead of
        # a 500.
        return AnalystCapacityImportResult(
            status=AnalystCapacityImportStatus.FAILED,
            error=str(result.result) if result.result else result.state,
        )
