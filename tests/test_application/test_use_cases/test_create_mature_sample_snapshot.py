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
from src.application.use_cases.datasets.create_mature_sample_snapshot import (
    CreateMatureSampleSnapshotUseCase,
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
    def __init__(self, rows: list[AlertRecord]) -> None:
        self.rows = rows

    def page_by_created_day(self, created_day, *, before, limit):
        rows = [
            row
            for row in self.rows
            if row.created_at.date() == created_day
            and (before is None or row.created_at < before)
        ]
        return sorted(rows, key=lambda row: row.created_at, reverse=True)[:limit]


class InMemorySchemas:
    def __init__(self) -> None:
        self.active = AlertSchemaVersion(
            version=3,
            status=AlertSchemaStatus.ACTIVE,
            fields=[
                AlertSchemaField(
                    id="field-id",
                    field="risk_band",
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
                    id="initial-mark",
                    field="reviewstatus_first",
                    data_source=AlertSchemaDataSource.ARIA,
                    type=AlertSchemaFieldType.STRING,
                    is_alert=True,
                ),
                AlertSchemaField(
                    id="initial-date",
                    field="fecha_primer_marcacion",
                    data_source=AlertSchemaDataSource.ARIA,
                    type=AlertSchemaFieldType.DATETIME,
                    is_alert=True,
                ),
                AlertSchemaField(
                    id="marked-on",
                    field="marked_on",
                    data_source=AlertSchemaDataSource.ARIA,
                    type=AlertSchemaFieldType.DATETIME,
                    is_alert=True,
                ),
            ],
        )

    def list_versions(self):
        return [self.active]

    def get_active(self):
        return self.active


class FixedOperationalSettings:
    def get(self):
        settings = OperationalSettings()
        settings.maturing_days = 4
        return settings


class FixedSamplerSettings:
    def get(self):
        return AssistantOptimizerSettings(
            sampler_strata=("risk_band",),
            sampler_period_days=30,
            sampler_minimum_per_stratum=1,
        )


class FixedSchemaMapping:
    def get(self):
        return MatureSamplerSchemaMapping(
            initial_mark_field="reviewstatus_first",
            initial_marking_date_field="fecha_primer_marcacion",
            target_field="outcome",
            marking_date_field="marked_on",
            label_value_mapping={"fraud": "fraud", "no fraud": "no_fraud"},
        )


class InMemoryDatasets:
    def __init__(self) -> None:
        self.rows = {}
        self.fields = {}
        self.create_count = 0

    def create(self, name, fields):
        self.create_count += 1
        self.rows[name] = []
        self.fields[name] = fields

    def append_rows(self, name, rows):
        self.rows[name].extend(rows)
        return len(self.rows[name])

    def delete(self, name):
        self.rows.pop(name, None)
        self.fields.pop(name, None)


class InMemorySnapshots:
    def __init__(self) -> None:
        self.rows = {}

    def get(self, snapshot_id):
        return self.rows.get(snapshot_id)

    def create(self, snapshot):
        self.rows[snapshot.snapshot_id] = snapshot
        return snapshot

    def list_recent(self, limit):
        return list(self.rows.values())[:limit]

    def delete(self, snapshot_id):
        self.rows.pop(snapshot_id, None)


class InMemorySamplerState:
    def __init__(self) -> None:
        self.value = None

    def get(self, state_id):
        return self.value

    def update(self, state: DatasetSamplerState):
        self.value = state
        return state


class FixedClock:
    def now(self):
        return datetime(2026, 10, 19, 12, tzinfo=UTC)


def _alert(day: date, *, label: Mark, risk: str) -> AlertRecord:
    created = datetime.combine(day, datetime.min.time(), tzinfo=UTC)
    return AlertRecord(
        id=uuid4(),
        event_id=str(uuid4()),
        event_type="test",
        status=AlertStatus.CLOSED,
        created_at=created,
        updated_at=created,
        input={
            "risk_band": risk,
            "reviewstatus_first": label.value.replace("_", " "),
            "fecha_primer_marcacion": created.isoformat(),
            "marked_on": created.isoformat(),
        },
        labels={"outcome": label.value.replace("_", " ")},
        schema_version=3,
        metrics=AlertMetricsSnapshot(fraud_label=label),
    )


def test_snapshot_materializes_four_partitions_and_is_idempotent() -> None:
    rows = [
        _alert(date(2026, 10, 1), label=Mark.FRAUD, risk="high"),
        _alert(date(2026, 10, 2), label=Mark.NO_FRAUD, risk="low"),
        _alert(date(2026, 10, 3), label=Mark.PENDING, risk="pending"),
        _alert(date(2026, 10, 18), label=Mark.FRAUD, risk="immature"),
    ]
    datasets = InMemoryDatasets()
    snapshots = InMemorySnapshots()
    state = InMemorySamplerState()
    use_case = CreateMatureSampleSnapshotUseCase(
        InMemoryAlerts(rows),
        InMemorySchemas(),
        FixedOperationalSettings(),
        FixedSamplerSettings(),
        datasets,
        snapshots,
        state,
        FixedSchemaMapping(),
        FixedClock(),
    )

    snapshot = use_case.execute(trigger="manual")
    created_datasets = datasets.create_count
    same_snapshot = use_case.execute(trigger="periodic")

    assert same_snapshot.snapshot_id == snapshot.snapshot_id
    assert datasets.create_count == created_datasets == 5
    assert set(snapshot.dataset_refs) == {"training", "validation", "test", "final", "all"}
    assert sum(snapshot.partition_counts.values()) == 2
    all_rows = datasets.rows[snapshot.dataset_refs["all"]]
    assert len(all_rows) == 2
    assert all(row["fraud_label"] in {"fraud", "no_fraud"} for row in all_rows)
    assert all(
        set(row)
        == {
            "risk_band",
            "reviewstatus_first",
            "fecha_primer_marcacion",
            "fraud_label",
            "__aria_partition",
        }
        for row in all_rows
    )
    assert state.value.last_snapshot_id == snapshot.snapshot_id
