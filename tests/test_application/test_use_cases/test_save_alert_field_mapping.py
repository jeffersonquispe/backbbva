from __future__ import annotations

from datetime import UTC, datetime

from src.application.dtos.alert_field_mapping_dtos import SaveAlertFieldMappingInput
from src.application.ports.alert_field_mapping_port import (
    AlertFieldMapping,
    AlertFieldMappingRepository,
)
from src.application.use_cases.datasets.save_alert_field_mapping import (
    SaveAlertFieldMappingUseCase,
)


class InMemoryAlertFieldMappingRepository(AlertFieldMappingRepository):
    def __init__(self, records: dict[str, AlertFieldMapping] | None = None) -> None:
        self._history = list(records.values()) if records is not None else []

    def get(self, dataset_name: str) -> AlertFieldMapping | None:
        records = [record for record in self._history if record.dataset_name == dataset_name]
        return max(
            records,
            key=lambda record: (
                record.updated_at.timestamp() if record.updated_at else float("-inf")
            ),
        ) if records else None

    def save(self, mapping: AlertFieldMapping) -> AlertFieldMapping:
        self._history.append(mapping)
        return mapping

    def delete(self, dataset_name: str) -> None:
        self._history = [record for record in self._history if record.dataset_name != dataset_name]


def test_save_alert_field_mapping_records_schema_version() -> None:
    repo = InMemoryAlertFieldMappingRepository()
    use_case = SaveAlertFieldMappingUseCase(repo)

    output = use_case.execute(
        SaveAlertFieldMappingInput(
            dataset_name="ds",
            schema_version=4,
            mappings={"eventId": "eventid"},
        )
    )

    assert output.dataset_name == "ds"
    assert output.schema_version == 4
    assert output.mappings == {"eventId": "eventid"}
    assert output.updated_at is not None
    assert output.updated_at.tzinfo is not None

    stored = repo.get("ds")
    assert stored is not None
    assert stored.mappings == {"eventId": "eventid"}
    assert stored.schema_version == 4
    assert stored.updated_at == output.updated_at
    assert len(repo._history) == 1


def test_save_alert_field_mapping_with_empty_mappings_clears_existing() -> None:
    existing_updated_at = datetime(2024, 1, 1, tzinfo=UTC)
    repo = InMemoryAlertFieldMappingRepository(
        {
            "ds": AlertFieldMapping(
                dataset_name="ds",
                schema_version=3,
                mappings={"eventId": "eventid"},
                updated_at=existing_updated_at,
            )
        }
    )
    use_case = SaveAlertFieldMappingUseCase(repo)

    output = use_case.execute(
        SaveAlertFieldMappingInput(dataset_name="ds", schema_version=4, mappings={})
    )

    assert output.mappings == {}

    stored = repo.get("ds")
    assert stored is not None
    assert stored.mappings == {}
    assert stored.updated_at != existing_updated_at


def test_save_alert_field_mapping_keeps_history_for_each_schema_version() -> None:
    repo = InMemoryAlertFieldMappingRepository()
    use_case = SaveAlertFieldMappingUseCase(repo)

    use_case.execute(SaveAlertFieldMappingInput("ds", 3, {"eventId": "old_id"}))
    use_case.execute(SaveAlertFieldMappingInput("ds", 4, {"eventId": "new_id"}))

    assert len(repo._history) == 2
    assert repo.get("ds").schema_version == 4
