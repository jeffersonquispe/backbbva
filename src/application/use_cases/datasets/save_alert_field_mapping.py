from __future__ import annotations

from src.application.ports.clock_port import Clock
from src.application.runtime_defaults import DEFAULT_CLOCK, resolve_clock



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
    def __init__(self, mapping_repository: AlertFieldMappingRepository, clock: Clock | None = None) -> None:
        self._mappings = mapping_repository
        self._clock = resolve_clock(clock)

    def execute(self, input: SaveAlertFieldMappingInput) -> SaveAlertFieldMappingOutput:
        now = self._clock.now()
        self._mappings.save(
            AlertFieldMapping(
                dataset_name=input.dataset_name,
                schema_version=input.schema_version,
                mappings=input.mappings,
                updated_at=now,
            )
        )
        return SaveAlertFieldMappingOutput(
            dataset_name=input.dataset_name,
            schema_version=input.schema_version,
            mappings=input.mappings,
            updated_at=now,
        )
