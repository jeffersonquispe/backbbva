from __future__ import annotations

from abc import ABC
from datetime import date

from src.application.ports.fraud_history_archive_port import ArchiveIndexEntry


class ArchiveIndexPort(ABC):
    def put_many(self, entries: list[ArchiveIndexEntry]) -> None:
        raise NotImplementedError

    def get(self, alert_id: str) -> ArchiveIndexEntry | None:
        raise NotImplementedError

    def find_by_event_id(self, event_id: str) -> list[ArchiveIndexEntry]:
        raise NotImplementedError

    def list_day(self, created_day: date, limit: int) -> list[ArchiveIndexEntry]:
        raise NotImplementedError
