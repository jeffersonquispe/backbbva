from datetime import UTC, datetime

from src.application.errors import ValidationError
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
from src.application.ports.audit_port import AuditEntry
from src.application.ports.clock_port import Clock
from src.application.use_cases.datasets.configure_mature_sampler_schema import (
    GetMatureSamplerSchemaConfigurationUseCase,
    UpdateMatureSamplerSchemaConfigurationUseCase,
)
from src.domain.datasets.mature_sample_entities import MatureSamplerSchemaMapping


class InMemorySchemas:
    def __init__(self):
        self.active = AlertSchemaVersion(
            version=4,
            status=AlertSchemaStatus.ACTIVE,
            fields=[
                AlertSchemaField(
                    id="target",
                    field="marcacion_final",
                    data_source=AlertSchemaDataSource.ARIA,
                    type=AlertSchemaFieldType.STRING,
                    is_label=True,
                ),
                AlertSchemaField(
                    id="marked-at",
                    field="fecha_ultima_marcacion",
                    data_source=AlertSchemaDataSource.ARIA,
                    type=AlertSchemaFieldType.DATETIME,
                ),
                AlertSchemaField(
                    id="feature",
                    field="customer_band",
                    data_source=AlertSchemaDataSource.ARIA,
                    type=AlertSchemaFieldType.STRING,
                ),
                AlertSchemaField(
                    id="private-date",
                    field="private_date",
                    data_source=AlertSchemaDataSource.ARIA,
                    type=AlertSchemaFieldType.DATE,
                    is_sensible=True,
                ),
            ],
        )

    def list_versions(self):
        return [self.active]

    def get_active(self):
        return self.active


class FixedSettings:
    def get(self):
        return AssistantOptimizerSettings()


class InMemoryMapping:
    def __init__(self):
        self.value = MatureSamplerSchemaMapping()

    def get(self):
        return self.value

    def update(self, value):
        self.value = value
        return value


class InMemoryChanges:
    def __init__(self):
        self.rows = []

    def append(self, change):
        self.rows.append(change)

    def list(self, limit=50):
        return list(reversed(self.rows))[:limit]


class InMemoryAudit:
    def __init__(self):
        self.rows: list[AuditEntry] = []

    def write(self, entry):
        self.rows.append(entry)


class FixedClock(Clock):
    def now(self):
        return datetime(2026, 10, 19, 12, tzinfo=UTC)


def test_schema_configuration_exposes_label_and_date_fields_but_not_sensitive_fields():
    mapping = InMemoryMapping()
    result = GetMatureSamplerSchemaConfigurationUseCase(
        InMemorySchemas(), FixedSettings(), mapping
    ).execute()

    assert [item["field"] for item in result["target_fields"]] == ["marcacion_final"]
    assert [item["field"] for item in result["marking_date_fields"]] == [
        "fecha_ultima_marcacion"
    ]
    assert result["mapping"]["target_field"] == ""


def test_update_persists_mapping_and_emits_diff_and_audit():
    schemas = InMemorySchemas()
    mapping = InMemoryMapping()
    changes = InMemoryChanges()
    audit = InMemoryAudit()
    use_case = UpdateMatureSamplerSchemaConfigurationUseCase(
        schemas, FixedSettings(), mapping, changes, audit, clock=FixedClock()
    )

    result = use_case.execute(
        MatureSamplerSchemaMapping(
            target_field="marcacion_final",
            marking_date_field="fecha_ultima_marcacion",
            label_value_mapping={"Fraude": "fraud", "No fraude": "no_fraud"},
        ),
        changed_by="manager@example.com",
    )

    assert result.label_value_mapping == {
        "fraude": "fraud",
        "no fraude": "no_fraud",
    }
    assert changes.rows[0].changed_by == "manager@example.com"
    assert changes.rows[0].changes[0].path == "sampler_schema_mapping"
    assert audit.rows[0].action == "mature_sampler.schema_mapping.update"


def test_update_rejects_fields_outside_schema_and_incomplete_class_mapping():
    mapping = InMemoryMapping()
    use_case = UpdateMatureSamplerSchemaConfigurationUseCase(
        InMemorySchemas(),
        FixedSettings(),
        mapping,
        InMemoryChanges(),
        InMemoryAudit(),
    )

    for proposed in (
        MatureSamplerSchemaMapping(
            target_field="invented_label",
            marking_date_field="fecha_ultima_marcacion",
            label_value_mapping={"fraude": "fraud", "no fraude": "no_fraud"},
        ),
        MatureSamplerSchemaMapping(
            target_field="marcacion_final",
            marking_date_field="private_date",
            label_value_mapping={"fraude": "fraud", "no fraude": "no_fraud"},
        ),
        MatureSamplerSchemaMapping(
            target_field="marcacion_final",
            marking_date_field="fecha_ultima_marcacion",
            label_value_mapping={"fraude": "fraud"},
        ),
    ):
        try:
            use_case.execute(proposed, changed_by="manager@example.com")
        except ValidationError:
            pass
        else:
            raise AssertionError("La configuración inválida debe rechazarse")


def test_update_allows_clearing_unconfigured_schema_mapping():
    mapping = InMemoryMapping()
    use_case = UpdateMatureSamplerSchemaConfigurationUseCase(
        InMemorySchemas(),
        FixedSettings(),
        mapping,
        InMemoryChanges(),
        InMemoryAudit(),
    )

    saved = use_case.execute(MatureSamplerSchemaMapping(), changed_by="manager@example.com")

    assert saved == MatureSamplerSchemaMapping()
