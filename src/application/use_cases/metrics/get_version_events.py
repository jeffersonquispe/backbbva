from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.application.ports.alert_schema_port import AlertSchemaRepository
from src.application.ports.configuration_port import ConfigurationRepository
from src.application.ports.version_events_port import VersionEvent


class GetVersionEvents:
    def __init__(
        self,
        schema_repository: AlertSchemaRepository,
        configuration_repository: ConfigurationRepository,
    ) -> None:
        self._schemas = schema_repository
        self._configurations = configuration_repository

    def execute(
        self, from_: datetime | None = None, to: datetime | None = None
    ) -> list[VersionEvent]:
        end = to or datetime.now(UTC)
        start = from_ or end - timedelta(days=1)
        if start.tzinfo is None:
            start = start.replace(tzinfo=UTC)
        if end.tzinfo is None:
            end = end.replace(tzinfo=UTC)
        events = [
            VersionEvent("schema", "Esquema", schema.version, None, schema.approved_at)
            for schema in self._schemas.list_versions()
            if schema.approved_at is not None and start <= schema.approved_at < end
        ]
        events.extend(
            VersionEvent(
                "configuration",
                config.name,
                config.version,
                config.configuration_id,
                config.activated_at,
            )
            for config in self._configurations.list_all_versions()
            if config.activated_at is not None and start <= config.activated_at < end
        )
        return sorted(events, key=lambda event: event.at)
