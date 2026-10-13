from __future__ import annotations

from src.application.ports.configuration_port import (
    ConfigurationRepository,
)
from src.domain.configurations.entities import (
    ConfigurationRecord,
)


class GetActiveConfigurationUseCase:
    def __init__(self, configuration_repository: ConfigurationRepository) -> None:
        self._configurations = configuration_repository

    def execute(self) -> ConfigurationRecord | None:
        return self._configurations.get_active()
