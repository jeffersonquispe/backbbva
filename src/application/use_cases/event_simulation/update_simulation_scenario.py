from __future__ import annotations

from src.application.dtos.simulation_dtos import UpdateSimulationScenarioInput
from src.application.errors import ConflictError, NotFoundError
from src.application.ports.simulation_scenario_port import (
    ScenarioStatus,
    SimulationScenarioRecord,
    SimulationScenarioRepository,
)


class UpdateSimulationScenarioUseCase:
    def __init__(self, scenario_repository: SimulationScenarioRepository) -> None:
        self._scenarios = scenario_repository

    def execute(self, input: UpdateSimulationScenarioInput) -> SimulationScenarioRecord:
        current = self._scenarios.get(input.scenario_id)
        if current is None:
            raise NotFoundError(f"Scenario {input.scenario_id} not found")
        if current.status == ScenarioStatus.RUNNING:
            raise ConflictError("Cannot edit a RUNNING scenario - pause it first")

        changes: dict = {}
        if input.name is not None:
            changes["name"] = input.name
        if input.rate_schedule is not None:
            changes["rate_schedule"] = input.rate_schedule
        if input.field_specs is not None:
            changes["field_specs"] = input.field_specs
        if input.target_dataset_name is not None:
            changes["target_dataset_name"] = input.target_dataset_name

        updated = self._scenarios.update(input.scenario_id, **changes)
        if updated is None:
            raise NotFoundError(f"Scenario {input.scenario_id} not found")
        return updated
