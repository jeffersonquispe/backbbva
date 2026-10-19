from datetime import UTC, date, datetime
from uuid import uuid4

from src.application.ports.alert_schema_port import (
    AlertSchemaDataSource,
    AlertSchemaField,
    AlertSchemaFieldType,
    AlertSchemaStatus,
    AlertSchemaVersion,
)
from src.application.ports.assistant_optimizer_settings_port import (
    AssistantOptimizerSettings,
)
from src.application.ports.operational_settings_port import OperationalSettings
from src.application.use_cases.datasets.preview_mature_sample import (
    PreviewMatureSampleUseCase,
)
from src.domain.alerts.entities import (
    AlertMetricsSnapshot,
    AlertRecord,
    AlertStatus,
    Mark,
)
from src.domain.datasets.mature_sample_entities import (
    DatasetSamplerState,
    MatureSamplerSchemaMapping,
)


class InMemoryAlerts:
    def __init__(self, alerts: list[AlertRecord]) -> None:
        self.alerts = alerts

    def page_by_created_day(
        self, created_day: date, *, before: datetime | None, limit: int
    ) -> list[AlertRecord]:
        matching = [
            item
            for item in self.alerts
            if item.created_at.date() == created_day
            and (before is None or item.created_at < before)
        ]
        return sorted(matching, key=lambda item: item.created_at, reverse=True)[:limit]


class FixedOperationalSettings:
    def get(self) -> OperationalSettings:
        settings = OperationalSettings()
        settings.maturing_days = 4
        return settings


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 1, 10, 12, tzinfo=UTC)


class InMemorySamplerState:
    def __init__(self, value: DatasetSamplerState | None = None) -> None:
        self.value = value

    def get(self, state_id: str):
        return self.value


class FixedSchemaMapping:
    def get(self):
        return MatureSamplerSchemaMapping(
            target_field="outcome",
            marking_date_field="marked_on",
            label_value_mapping={"fraud": "fraud", "no fraud": "no_fraud"},
        )


class FixedSamplerSettings:
    def __init__(self, settings: AssistantOptimizerSettings) -> None:
        self.settings = settings

    def get(self) -> AssistantOptimizerSettings:
        return self.settings


class InMemoryAlertSchemas:
    def __init__(self) -> None:
        self.active = AlertSchemaVersion(
            version=3,
            status=AlertSchemaStatus.ACTIVE,
            fields=[
                AlertSchemaField(
                    id="f1",
                    field="risk_band",
                    field_name="risk_band",
                    data_source=AlertSchemaDataSource.ARIA,
                    type=AlertSchemaFieldType.STRING,
                    is_alert=True,
                ),
                AlertSchemaField(
                    id="target",
                    field="outcome",
                    data_source=AlertSchemaDataSource.ARIA,
                    type=AlertSchemaFieldType.STRING,
                    is_alert=True,
                    is_label=True,
                ),
                AlertSchemaField(
                    id="marked-on",
                    field="marked_on",
                    data_source=AlertSchemaDataSource.ARIA,
                    type=AlertSchemaFieldType.DATETIME,
                    is_alert=True,
                ),
                AlertSchemaField(
                    id="f2",
                    field="device_type",
                    field_name="device_type",
                    data_source=AlertSchemaDataSource.ARIA,
                    type=AlertSchemaFieldType.STRING,
                    is_alert=True,
                ),
                AlertSchemaField(
                    id="f3",
                    field="private_value",
                    field_name="private_value",
                    data_source=AlertSchemaDataSource.ARIA,
                    type=AlertSchemaFieldType.STRING,
                    is_alert=True,
                    is_sensible=True,
                ),
            ],
        )

    def get_active(self) -> AlertSchemaVersion:
        return self.active

    def list_versions(self) -> list[AlertSchemaVersion]:
        return [self.active]


def _alert(
    day: int, label: Mark, *, reviewed_at: datetime | None = None
) -> AlertRecord:
    created = datetime(2026, 1, day, tzinfo=UTC)
    return AlertRecord(
        id=uuid4(),
        event_id=str(uuid4()),
        event_type="test",
        status=AlertStatus.CLOSED,
        created_at=created,
        updated_at=created,
        input={
            "risk_band": "high",
            "device_type": "mobile",
            "outcome": label.value.replace("_", " "),
            "marked_on": created.isoformat(),
        },
        metrics=AlertMetricsSnapshot(
            fraud_label=label, fraud_reviewed_at=reviewed_at
        ),
    )


def test_preview_returns_only_aggregates_and_excludes_pending_or_immature() -> None:
    settings = AssistantOptimizerSettings(
        sampler_enabled=True,
        sampler_period_days=6,
        sampler_strata=("risk_band", "device_type"),
        sampler_period_trigger_enabled=False,
    )
    use_case = PreviewMatureSampleUseCase(
        InMemoryAlerts(
            [_alert(1, Mark.FRAUD), _alert(2, Mark.NO_FRAUD), _alert(8, Mark.FRAUD)]
        ),
        FixedOperationalSettings(),
        FixedSamplerSettings(settings),
        InMemoryAlertSchemas(),
        InMemorySamplerState(),
        FixedSchemaMapping(),
        FixedClock(),
        "America/Bogota",
    )

    result = use_case.execute(as_of=date(2026, 1, 10))

    assert result.eligible_alerts == 2
    assert result.estimated_sample_size == 2
    assert result.counts_by_stratum == {"high | mobile": 2}
    assert result.active_triggers == []
    assert not hasattr(result, "rows")


def test_preview_rejects_fields_outside_manager_schema_pool() -> None:
    settings = AssistantOptimizerSettings(sampler_strata=("private_value",))
    use_case = PreviewMatureSampleUseCase(
        InMemoryAlerts([]),
        FixedOperationalSettings(),
        FixedSamplerSettings(settings),
        InMemoryAlertSchemas(),
        InMemorySamplerState(),
        FixedSchemaMapping(),
        FixedClock(),
        "America/Bogota",
    )

    try:
        use_case.execute(as_of=date(2026, 1, 10))
    except ValueError as exc:
        assert "esquema compatible" in str(exc)
    else:
        raise AssertionError("El campo sensible no debe estar en el pool seleccionable")


def test_preview_evaluates_periodic_and_newly_matured_volume_triggers() -> None:
    settings = AssistantOptimizerSettings(
        sampler_enabled=True,
        sampler_period_days=6,
        sampler_strata=("risk_band",),
        sampler_period_trigger_interval_days=7,
        sampler_volume_trigger_enabled=True,
        sampler_volume_threshold=1,
    )
    state = DatasetSamplerState(
        state_id="current",
        last_completed_at=datetime(2026, 1, 1, tzinfo=UTC),
        matured_alert_count=10,
    )
    use_case = PreviewMatureSampleUseCase(
        InMemoryAlerts(
            [
                _alert(1, Mark.FRAUD, reviewed_at=datetime(2026, 1, 5, tzinfo=UTC)),
                _alert(2, Mark.NO_FRAUD, reviewed_at=datetime(2026, 1, 5, tzinfo=UTC)),
            ]
        ),
        FixedOperationalSettings(),
        FixedSamplerSettings(settings),
        InMemoryAlertSchemas(),
        InMemorySamplerState(state),
        FixedSchemaMapping(),
        FixedClock(),
        "America/Bogota",
    )

    result = use_case.execute(as_of=date(2026, 1, 10))

    assert result.active_triggers == ["periodic", "volume"]
