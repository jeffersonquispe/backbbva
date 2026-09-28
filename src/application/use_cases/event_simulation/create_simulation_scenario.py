from __future__ import annotations

import uuid
from datetime import datetime, timezone

from src.application.dtos.simulation_dtos import CreateSimulationScenarioInput
from src.application.ports.simulation_scenario_port import (
    OutputMode,
    ScenarioStatus,
    SimulationScenarioRecord,
    SimulationScenarioRepository,
)


class CreateSimulationScenarioUseCase:
    def __init__(self, scenario_repository: SimulationScenarioRepository) -> None:
        self._scenarios = scenario_repository

    def execute(self, input: CreateSimulationScenarioInput) -> SimulationScenarioRecord:
        if input.output_mode == OutputMode.DATASET and not input.target_dataset_name:
            raise ValueError("target_dataset_name is required when output_mode is DATASET")

        now = datetime.now(timezone.utc)
        return self._scenarios.create(
            SimulationScenarioRecord(
                id=uuid.uuid4(),
                name=input.name,
                status=ScenarioStatus.DRAFT,
                output_mode=input.output_mode,
                rate_schedule=input.rate_schedule,
                field_specs=input.field_specs,
                target_dataset_name=input.target_dataset_name,
                created_by=input.created_by,
                created_at=now,
                updated_at=now,
            )
        )
