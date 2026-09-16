from __future__ import annotations

from src.application.ports.operational_settings_port import (
    OperationalSettings,
    OperationalSettingsRepository,
)


class GetOperationalSettingsUseCase:
    def __init__(self, repository: OperationalSettingsRepository) -> None:
        self._repository = repository

    def execute(self) -> OperationalSettings:
        return self._repository.get()
