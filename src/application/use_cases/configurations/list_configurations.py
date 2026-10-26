from __future__ import annotations

from src.application.ports.configuration_port import (
    ConfigurationRepository,
)
from src.domain.configurations.entities import (
    ConfigurationRecord,
)


class ListConfigurationsUseCase:
    """One row per configuration lineage, at its newest version."""

    def __init__(self, configuration_repository: ConfigurationRepository) -> None:
        self._configurations = configuration_repository

    def execute(self) -> list[ConfigurationRecord]:
        return sorted(
            self._configurations.list_latest(),
            key=lambda config: config.name,
        )
