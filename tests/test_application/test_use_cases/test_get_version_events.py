from datetime import UTC, datetime, timedelta

from src.application.ports.alert_schema_port import (
    AlertSchemaStatus,
    AlertSchemaVersion,
)
from src.application.use_cases.metrics.get_version_events import GetVersionEvents
from src.domain.configurations.entities import (
    ConfigurationRecord,
    GeneralSettings,
    InfraSettings,
    TestSettings,
)


class InMemorySchemaRepository:
    def __init__(self, versions):
        self.versions = versions

    def list_versions(self):
        return list(self.versions)


class InMemoryConfigurationRepository:
    def __init__(self, versions):
        self.versions = versions

    def list_all_versions(self):
        return list(self.versions)


def _configuration(version: int, activated_at: datetime | None) -> ConfigurationRecord:
    now = datetime(2026, 10, 9, tzinfo=UTC)
    return ConfigurationRecord(
        configuration_id="cfg-x",
        version=version,
        name="X",
        description="",
        active=version == 2,
        general=GeneralSettings(),
        infra=InfraSettings(),
        test=TestSettings(),
        created_at=now,
        updated_at=now,
        activated_at=activated_at,
    )


def test_lists_schema_and_configuration_activations_in_range_sorted_by_time():
    start = datetime(2026, 10, 9, 10, tzinfo=UTC)
    schema_at = start + timedelta(minutes=5)
    config_at = start + timedelta(minutes=10)
    use_case = GetVersionEvents(
        InMemorySchemaRepository(
            [
                AlertSchemaVersion(
                    version=3,
                    status=AlertSchemaStatus.ACTIVE,
                    approved_at=schema_at,
                ),
                AlertSchemaVersion(version=1),
            ]
        ),
        InMemoryConfigurationRepository(
            [_configuration(2, config_at), _configuration(1, None)]
        ),
    )

    events = use_case.execute(start, start + timedelta(hours=1))

    assert [(event.kind, event.label, event.version) for event in events] == [
        ("schema", "Esquema", 3),
        ("configuration", "X", 2),
    ]
    assert events[1].configuration_id == "cfg-x"


def test_defaults_to_last_24_hours_and_excludes_events_without_activation_time():
    now = datetime.now(UTC)
    use_case = GetVersionEvents(
        InMemorySchemaRepository([AlertSchemaVersion(version=2)]),
        InMemoryConfigurationRepository([_configuration(1, None)]),
    )

    assert use_case.execute(now - timedelta(seconds=1), now) == []
