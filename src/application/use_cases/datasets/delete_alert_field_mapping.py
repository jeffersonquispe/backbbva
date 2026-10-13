from __future__ import annotations

from src.application.ports.alert_field_mapping_port import AlertFieldMappingRepository


class DeleteAlertFieldMappingUseCase:
    def __init__(self, mapping_repository: AlertFieldMappingRepository) -> None:
        self._mappings = mapping_repository

    def execute(self, dataset_name: str) -> None:
        self._mappings.delete(dataset_name)
