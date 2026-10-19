from __future__ import annotations

from datetime import date
from typing import Protocol

from src.application.ports.alert_schema_port import AlertSchemaPresenceReport


class AlertSchemaPresenceReportRepository(Protocol):
    def save(self, report: AlertSchemaPresenceReport) -> AlertSchemaPresenceReport: ...
    def get(self, report_day: date) -> AlertSchemaPresenceReport | None: ...
    def get_latest(self) -> AlertSchemaPresenceReport | None: ...
    def list_before(
        self, report_day: date, limit: int = 30
    ) -> list[AlertSchemaPresenceReport]: ...
