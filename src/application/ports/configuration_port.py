from __future__ import annotations

from typing import Protocol

from src.domain.configurations.entities import (
    ConfigurationRecord,
)


class ConfigurationRepository(Protocol):
    """Persistence contract for versioned configurations."""

    def create(self, config: ConfigurationRecord) -> ConfigurationRecord: ...

    def mark_tested(self, configuration_id: str, version: int) -> None: ...

    def get(
        self, configuration_id: str, version: int
    ) -> ConfigurationRecord | None: ...

    def get_latest_version(
        self, configuration_id: str
    ) -> ConfigurationRecord | None: ...

    def get_active(self) -> ConfigurationRecord | None: ...

    def list_latest(self) -> list[ConfigurationRecord]: ...

    def list_versions(self, configuration_id: str) -> list[ConfigurationRecord]: ...

    def list_all_versions(self) -> list[ConfigurationRecord]: ...

    def activate(
        self,
        configuration_id: str,
        version: int,
        expected_current: tuple[str, int] | None = None,
    ) -> ConfigurationRecord: ...
