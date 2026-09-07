from __future__ import annotations

from src.application.dtos.alert_field_mapping_dtos import GetAlertFieldMappingOutput
from src.application.ports.alert_field_mapping_port import AlertFieldMappingRepository


class GetAlertFieldMappingUseCase:
    def __init__(self, mapping_repository: AlertFieldMappingRepository) -> None:
        self._mappings = mapping_repository

    def execute(self, dataset_name: str) -> GetAlertFieldMappingOutput:
        mapping = self._mappings.get(dataset_name)
        if mapping is None:
            return GetAlertFieldMappingOutput(
                dataset_name=dataset_name,
                mappings={},
                updated_at=None,
            )
        return GetAlertFieldMappingOutput(
            dataset_name=mapping.dataset_name,
            mappings=mapping.mappings,
            updated_at=mapping.updated_at,
        )
