from typing import Any

from src.application.ports.alert_schema_port import (
    AlertSchemaDataSource,
    AlertSchemaField,
    AlertSchemaFieldType,
    AlertSchemaVersion,
)
from src.application.use_cases.event_simulation.seed_simulation_from_dataset import (
    SeedSimulationFromDatasetUseCase,
)


class InMemoryDatasetRepository:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def get_rows(self, name: str) -> list[dict[str, Any]]:
        return self.rows


class InMemorySchemaRepository:
    def __init__(self, schema: AlertSchemaVersion) -> None:
        self.schema = schema

    def get_active(self) -> AlertSchemaVersion:
        return self.schema


def test_seed_uses_frequencies_numeric_criterion_and_excludes_labels() -> None:
    schema = AlertSchemaVersion(
        version=2,
        fields=[
            AlertSchemaField(
                "channel",
                AlertSchemaDataSource.ARIC,
                "channel",
                field_ds_loc="event.channel",
            ),
            AlertSchemaField(
                "amount",
                AlertSchemaDataSource.ARIC,
                "amount",
                field_ds_loc="amount",
                type=AlertSchemaFieldType.NUMBER,
            ),
            AlertSchemaField(
                "label",
                AlertSchemaDataSource.ARIC,
                "label",
                field_ds_loc="label",
                is_label=True,
            ),
        ],
    )
    rows = [
        {"event": {"channel": "app"}, "amount": 0},
        {"event": {"channel": "app"}, "amount": 1},
        {"event": {"channel": "web"}, "amount": 1},
    ]

    specs = SeedSimulationFromDatasetUseCase(
        InMemoryDatasetRepository(rows), InMemorySchemaRepository(schema)
    ).execute("training")

    assert specs["event.channel"].weights == {"app": 2.0, "web": 1.0}
    assert specs["amount"].kind.value == "POISSON"
    assert specs.keys() == {"event.channel", "amount"}


def test_sensitive_field_gets_synthetic_values_not_dataset_values() -> None:
    schema = AlertSchemaVersion(
        version=2,
        fields=[
            AlertSchemaField(
                "customer",
                AlertSchemaDataSource.ARIC,
                "customer_id",
                field_ds_loc="customer.id",
                is_sensible=True,
                sensitivity_strategy="anonymize",
            )
        ],
    )

    specs = SeedSimulationFromDatasetUseCase(
        InMemoryDatasetRepository([{"customer": {"id": "real-id"}}]),
        InMemorySchemaRepository(schema),
    ).execute("training")

    assert "real-id" not in specs["customer.id"].weights
    assert all(
        value.startswith("synthetic_customer_id_")
        for value in specs["customer.id"].weights
    )
