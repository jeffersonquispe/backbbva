from __future__ import annotations

from datetime import datetime, timezone

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
        self._records = records if records is not None else {}

    def get(self, dataset_name: str) -> AlertFieldMapping | None:
        return self._records.get(dataset_name)

    def upsert(self, mapping: AlertFieldMapping) -> AlertFieldMapping:
        self._records[mapping.dataset_name] = mapping
        return mapping

    def delete(self, dataset_name: str) -> None:
        self._records.pop(dataset_name, None)


def test_save_alert_field_mapping_upserts_and_returns_saved_shape() -> None:
    repo = InMemoryAlertFieldMappingRepository()
    use_case = SaveAlertFieldMappingUseCase(repo)

    output = use_case.execute(
        SaveAlertFieldMappingInput(
            dataset_name="ds",
            mappings={"eventId": "eventid"},
        )
    )

    assert output.dataset_name == "ds"
    assert output.mappings == {"eventId": "eventid"}
    assert output.updated_at is not None
    assert output.updated_at.tzinfo is not None

    stored = repo.get("ds")
    assert stored is not None
    assert stored.mappings == {"eventId": "eventid"}
    assert stored.updated_at == output.updated_at


def test_save_alert_field_mapping_with_empty_mappings_clears_existing() -> None:
    existing_updated_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    repo = InMemoryAlertFieldMappingRepository(
        {
            "ds": AlertFieldMapping(
                dataset_name="ds",
                mappings={"eventId": "eventid"},
                updated_at=existing_updated_at,
            )
        }
    )
    use_case = SaveAlertFieldMappingUseCase(repo)

    output = use_case.execute(
        SaveAlertFieldMappingInput(dataset_name="ds", mappings={})
    )

    assert output.mappings == {}

    stored = repo.get("ds")
    assert stored is not None
    assert stored.mappings == {}
    assert stored.updated_at != existing_updated_at
