from __future__ import annotations

from src.application.ports.simulation_scenario_port import (
    ScenarioStatus,
    SimulationScenarioRecord,
    SimulationScenarioRepository,
)


class ListSimulationScenariosUseCase:
    def __init__(self, scenario_repository: SimulationScenarioRepository) -> None:
        self._scenarios = scenario_repository

    def execute(self, status: ScenarioStatus | None = None) -> list[SimulationScenarioRecord]:
        return self._scenarios.list(status=status)
