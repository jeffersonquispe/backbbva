from __future__ import annotations

from datetime import UTC, datetime

from src.application.ports.alert_field_mapping_port import (
    AlertFieldMapping,
    AlertFieldMappingRepository,
)
from src.application.use_cases.datasets.get_alert_field_mapping import (
    GetAlertFieldMappingUseCase,
)


class InMemoryAlertFieldMappingRepository(AlertFieldMappingRepository):
    def __init__(self, records: dict[str, AlertFieldMapping] | None = None) -> None:
        self._records = records if records is not None else {}

    def get(self, dataset_name: str) -> AlertFieldMapping | None:
        return self._records.get(dataset_name)

    def save(self, mapping: AlertFieldMapping) -> AlertFieldMapping:
        self._records[mapping.dataset_name] = mapping
        return mapping

    def delete(self, dataset_name: str) -> None:
        self._records.pop(dataset_name, None)


def test_get_alert_field_mapping_returns_empty_mapping_when_none_saved() -> None:
    repo = InMemoryAlertFieldMappingRepository()
    use_case = GetAlertFieldMappingUseCase(repo)

    output = use_case.execute("ds")

    assert output.dataset_name == "ds"
    assert output.mappings == {}
    assert output.updated_at is None


def test_get_alert_field_mapping_returns_existing_mapping_as_is() -> None:
    updated_at = datetime(2024, 1, 1, tzinfo=UTC)
    repo = InMemoryAlertFieldMappingRepository(
        {
            "ds": AlertFieldMapping(
                dataset_name="ds",
                schema_version=4,
                mappings={"eventId": "eventid"},
                updated_at=updated_at,
            )
        }
    )
    use_case = GetAlertFieldMappingUseCase(repo)

    output = use_case.execute("ds")

    assert output.dataset_name == "ds"
    assert output.schema_version == 4
    assert output.mappings == {"eventId": "eventid"}
    assert output.updated_at == updated_at
