from datetime import datetime, timezone

import pytest

from src.application.dtos.configuration_dtos import CreateConfigurationInput
from src.application.ports.configuration_port import (
    ConfigurationRecord,
    GeneralSettings,
    InfraSettings,
    OpsSettings,
    TestSettings as ConfigurationTestSettings,
)
from src.application.use_cases.configurations.create_configuration import (
    ConfigurationVersionConflictError,
)
from src.application.use_cases.configurations.test_configuration import (
    HIGH_IMPACT_WARNING,
    PreviewConfigurationUseCase,
)


class InMemoryConfigurationRepository:
    def __init__(self, record: ConfigurationRecord) -> None:
        self.record = record

    def get_latest_version(self, configuration_id: str) -> ConfigurationRecord | None:
        return self.record if configuration_id == self.record.configuration_id else None


def _record() -> ConfigurationRecord:
    now = datetime.now(timezone.utc)
    return ConfigurationRecord(
        configuration_id="cfg-1",
        version=2,
        name="Producción",
        description="Configuración activa",
        active=True,
        general=GeneralSettings(),
        infra=InfraSettings(),
        ops=OpsSettings(),
        test=ConfigurationTestSettings(),
        segments={},
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
            ops=OpsSettings(),
            test=ConfigurationTestSettings(max_test_instances=8),
            segments={},
        )
    )

    assert result.valid is True
    assert [(change.path, change.previous, change.proposed) for change in result.changes] == [
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
            ops=OpsSettings(),
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
