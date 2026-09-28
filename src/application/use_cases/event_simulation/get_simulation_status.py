from __future__ import annotations

from uuid import UUID

from src.application.dtos.simulation_dtos import SimulationStatusOutput
from src.application.ports.simulation_scenario_port import SimulationScenarioRepository


class GetSimulationStatusUseCase:
    def __init__(self, scenario_repository: SimulationScenarioRepository) -> None:
        self._scenarios = scenario_repository

    def execute(self, scenario_id: UUID) -> SimulationStatusOutput:
        scenario = self._scenarios.get(scenario_id)
        if scenario is None:
            raise LookupError(f"Scenario {scenario_id} not found")
        return SimulationStatusOutput(
            scenario_id=scenario.id,
            status=scenario.status,
            events_emitted=scenario.events_emitted,
            last_tick_offset_seconds=scenario.last_tick_offset_seconds,
            error=scenario.error,
        )
