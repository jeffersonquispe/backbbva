from __future__ import annotations

from uuid import UUID

from src.application.ports.simulation_scenario_port import (
    SimulationScenarioRecord,
    SimulationScenarioRepository,
)


class GetSimulationScenarioUseCase:
    def __init__(self, scenario_repository: SimulationScenarioRepository) -> None:
        self._scenarios = scenario_repository

    def execute(self, scenario_id: UUID) -> SimulationScenarioRecord | None:
        return self._scenarios.get(scenario_id)
