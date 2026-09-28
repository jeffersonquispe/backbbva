from __future__ import annotations

from uuid import UUID

from src.application.ports.simulation_scenario_port import (
    ScenarioStatus,
    SimulationScenarioRecord,
    SimulationScenarioRepository,
)


class StopSimulationUseCase:
    """Terminal stop - unlike pause, a stopped scenario cannot be resumed
    (create a new one instead). The tick task's status check stops it the
    same way a pause does."""

    def __init__(self, scenario_repository: SimulationScenarioRepository) -> None:
        self._scenarios = scenario_repository

    def execute(self, scenario_id: UUID) -> SimulationScenarioRecord:
        scenario = self._scenarios.get(scenario_id)
        if scenario is None:
            raise LookupError(f"Scenario {scenario_id} not found")
        if scenario.status == ScenarioStatus.COMPLETED:
            return scenario
        updated = self._scenarios.update(scenario_id, status=ScenarioStatus.COMPLETED)
        return updated
