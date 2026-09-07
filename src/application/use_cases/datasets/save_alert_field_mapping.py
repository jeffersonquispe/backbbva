from __future__ import annotations

from datetime import datetime, timezone

from src.application.dtos.alert_field_mapping_dtos import (
    SaveAlertFieldMappingInput,
    SaveAlertFieldMappingOutput,
)
from src.application.ports.alert_field_mapping_port import (
    AlertFieldMapping,
    AlertFieldMappingRepository,
)


class SaveAlertFieldMappingUseCase:
    def __init__(self, mapping_repository: AlertFieldMappingRepository) -> None:
        self._mappings = mapping_repository

    def execute(self, input: SaveAlertFieldMappingInput) -> SaveAlertFieldMappingOutput:
        now = datetime.now(timezone.utc)
        self._mappings.upsert(
            AlertFieldMapping(
                dataset_name=input.dataset_name,
                mappings=input.mappings,
                updated_at=now,
            )
        )
        return SaveAlertFieldMappingOutput(
            dataset_name=input.dataset_name,
            mappings=input.mappings,
            updated_at=now,
        )
