from __future__ import annotations

from uuid import UUID

from src.application.ports.simulation_scenario_port import (
    ScenarioStatus,
    SimulationScenarioRepository,
)


class DeleteSimulationScenarioUseCase:
    def __init__(self, scenario_repository: SimulationScenarioRepository) -> None:
        self._scenarios = scenario_repository

    def execute(self, scenario_id: UUID) -> None:
        current = self._scenarios.get(scenario_id)
        if current is not None and current.status == ScenarioStatus.RUNNING:
            raise ValueError("Cannot delete a RUNNING scenario - stop it first")
        self._scenarios.delete(scenario_id)
