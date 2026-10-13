from __future__ import annotations

from uuid import UUID

from src.application.errors import NotFoundError
from src.application.ports.simulation_scenario_port import (
    ScenarioStatus,
    SimulationScenarioRecord,
    SimulationScenarioRepository,
)


class PauseSimulationUseCase:
    """Flips a RUNNING scenario to PAUSED - the tick task checks this status
    on every iteration and simply stops rescheduling itself once it's no
    longer RUNNING, rather than being forcibly cancelled."""

    def __init__(self, scenario_repository: SimulationScenarioRepository) -> None:
        self._scenarios = scenario_repository

    def execute(self, scenario_id: UUID) -> SimulationScenarioRecord:
        scenario = self._scenarios.get(scenario_id)
        if scenario is None:
            raise NotFoundError(f"Scenario {scenario_id} not found")
        if scenario.status != ScenarioStatus.RUNNING:
            return scenario
        updated = self._scenarios.update(scenario_id, status=ScenarioStatus.PAUSED)
        return updated
