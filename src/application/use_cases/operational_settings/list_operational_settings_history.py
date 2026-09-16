from __future__ import annotations

from src.application.ports.operational_settings_port import (
    OperationalSettingsChange,
    OperationalSettingsRepository,
)


class ListOperationalSettingsHistoryUseCase:
    def __init__(self, repository: OperationalSettingsRepository) -> None:
        self._repository = repository

    def execute(self, limit: int = 50) -> list[OperationalSettingsChange]:
        return self._repository.list_changes(limit)
