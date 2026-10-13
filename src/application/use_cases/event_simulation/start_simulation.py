from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from src.application.ports.simulation_dispatcher_port import SimulationDispatcher
from src.application.ports.simulation_scenario_port import (
    ScenarioStatus,
    SimulationScenarioRecord,
    SimulationScenarioRepository,
)


class StartSimulationUseCase:
    """Starts a DRAFT scenario, or resumes a PAUSED one from where it left
    off - started_at/last_tick_offset_seconds are only ever set once (on the
    very first start), so a pause/resume cycle never restarts the rate
    curve from minute 0."""

    def __init__(
        self,
        scenario_repository: SimulationScenarioRepository,
        dispatcher: SimulationDispatcher,
    ) -> None:
        self._scenarios = scenario_repository
        self._dispatcher = dispatcher

    def execute(self, scenario_id: UUID) -> SimulationScenarioRecord:
        scenario = self._scenarios.get(scenario_id)
        if scenario is None:
            raise LookupError(f"Scenario {scenario_id} not found")
        if scenario.status == ScenarioStatus.RUNNING:
            return scenario
        if scenario.status == ScenarioStatus.COMPLETED:
            raise ValueError("Cannot restart a COMPLETED scenario - create a new one")

        updated = self._scenarios.update(
            scenario_id,
            status=ScenarioStatus.RUNNING,
            started_at=scenario.started_at or datetime.now(UTC),
            error=None,
        )
        self._dispatcher.dispatch(scenario_id)
        return updated
