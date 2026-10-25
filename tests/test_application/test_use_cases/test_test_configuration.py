from datetime import UTC, datetime

import pytest

from src.application.dtos.configuration_dtos import CreateConfigurationInput
from src.application.ports.alert_schema_port import (
    AlertSchemaStatus,
    AlertSchemaVersion,
)
from src.application.use_cases.configurations.create_configuration import (
    ConfigurationVersionConflictError,
)
from src.application.use_cases.configurations.test_configuration import (
    HIGH_IMPACT_WARNING,
    SCHEMA_VERSION_WARNING,
    PreviewConfigurationUseCase,
)
from src.domain.configurations.entities import (
    ConfigurationRecord,
    GeneralSettings,
    InfraSettings,
)
from src.domain.configurations.entities import (
    TestSettings as ConfigurationTestSettings,
)


class InMemoryConfigurationRepository:
    def __init__(self, record: ConfigurationRecord) -> None:
        self.record = record

    def get_latest_version(self, configuration_id: str) -> ConfigurationRecord | None:
        return self.record if configuration_id == self.record.configuration_id else None

    def get(self, configuration_id: str, version: int) -> ConfigurationRecord | None:
        if configuration_id == self.record.configuration_id and version == self.record.version:
            return self.record
        return None


def _record() -> ConfigurationRecord:
    now = datetime.now(UTC)
    return ConfigurationRecord(
        configuration_id="cfg-1",
        version=2,
        name="Producción",
        description="Configuración activa",
        active=True,
        general=GeneralSettings(),
        infra=InfraSettings(),
        test=ConfigurationTestSettings(),
        segments={},
        schema_version_at_creation=3,
        created_at=now,
        updated_at=now,
    )


def test_reports_only_changed_values_and_high_impact_warning() -> None:
    use_case = PreviewConfigurationUseCase(InMemoryConfigurationRepository(_record()))

    result = use_case.execute(
        CreateConfigurationInput(
            configuration_id="cfg-1",
            based_on_version=2,
            name="Producción",
            description="Configuración activa",
            general=GeneralSettings(),
            infra=InfraSettings(max_instances=12),
            test=ConfigurationTestSettings(max_test_instances=8),
            segments={},
        )
    )

    assert result.valid is True
    assert [
        (change.path, change.previous, change.proposed) for change in result.changes
    ] == [
        ("infra.max_instances", 8, 12),
        ("test.max_test_instances", 4, 8),
    ]
    assert result.warnings == [HIGH_IMPACT_WARNING]


def test_non_critical_change_has_no_warning() -> None:
    use_case = PreviewConfigurationUseCase(InMemoryConfigurationRepository(_record()))

    result = use_case.execute(
        CreateConfigurationInput(
            configuration_id="cfg-1",
            based_on_version=2,
            name="Producción QA",
            description="Configuración activa",
            general=GeneralSettings(),
            infra=InfraSettings(),
            test=ConfigurationTestSettings(),
            segments={},
        )
    )

    assert [change.path for change in result.changes] == ["name"]
    assert result.warnings == []


def test_rejects_a_stale_base_version() -> None:
    use_case = PreviewConfigurationUseCase(InMemoryConfigurationRepository(_record()))

    with pytest.raises(ConfigurationVersionConflictError):
        use_case.execute(
            CreateConfigurationInput(
                configuration_id="cfg-1",
                based_on_version=1,
                name="Producción",
            )
        )


def test_warns_when_testing_against_a_different_active_alert_schema() -> None:
    class InMemoryAlertSchemaRepository:
        def get_active(self):
            return AlertSchemaVersion(version=4, status=AlertSchemaStatus.ACTIVE)

    result = PreviewConfigurationUseCase(
        InMemoryConfigurationRepository(_record()), InMemoryAlertSchemaRepository()
    ).execute(
        CreateConfigurationInput(
            configuration_id="cfg-1",
            based_on_version=2,
            name="Producción",
            description="Configuración activa",
            general=GeneralSettings(),
            infra=InfraSettings(),
            test=ConfigurationTestSettings(),
            segments={},
        )
    )

    assert result.warnings == [SCHEMA_VERSION_WARNING.format(created=3, active=4)]


def test_does_not_warn_when_active_schema_matches_creation_schema() -> None:
    class InMemoryAlertSchemaRepository:
        def get_active(self):
            return AlertSchemaVersion(version=3, status=AlertSchemaStatus.ACTIVE)

    result = PreviewConfigurationUseCase(
        InMemoryConfigurationRepository(_record()), InMemoryAlertSchemaRepository()
    ).execute(
        CreateConfigurationInput(
            configuration_id="cfg-1",
            based_on_version=2,
            name="Producción",
            description="Configuración activa",
            general=GeneralSettings(),
            infra=InfraSettings(),
            test=ConfigurationTestSettings(),
            segments={},
        )
    )

    assert result.warnings == []
