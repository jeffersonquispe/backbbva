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

    def execute_graph(self) -> list[ConfigurationRecord]:
        """Return every immutable version for the read-only version graph."""
        return sorted(
            self._configurations.list_all_versions(),
            key=lambda config: (config.created_at, config.configuration_id, config.version),
        )
