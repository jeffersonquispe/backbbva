from __future__ import annotations

from uuid import UUID

from src.application.ports.simulation_scenario_port import (
    ScenarioStatus,
    SimulationScenarioRecord,
    SimulationScenarioRepository,
)


class RecordTickResultUseCase:
    """Applies one tick's outcome to a scenario's progress - called by the
    Celery tick task after it generates+writes a batch (or fails to), so
    that state-transition logic (when a scenario becomes COMPLETED/FAILED)
    lives here, testable in isolation, not inline in tasks.py."""

    def __init__(self, scenario_repository: SimulationScenarioRepository) -> None:
        self._scenarios = scenario_repository

    def execute(
        self,
        scenario_id: UUID,
        *,
        events_generated: int,
        tick_offset_seconds: int,
        schedule_exhausted: bool,
    ) -> SimulationScenarioRecord:
        scenario = self._scenarios.get(scenario_id)
        if scenario is None:
            raise LookupError(f"Scenario {scenario_id} not found")

        new_status = ScenarioStatus.COMPLETED if schedule_exhausted else scenario.status
        updated = self._scenarios.update(
            scenario_id,
            events_emitted=scenario.events_emitted + events_generated,
            last_tick_offset_seconds=tick_offset_seconds,
            status=new_status,
        )
        if updated is None:
            raise LookupError(f"Scenario {scenario_id} not found")
        return updated

    def record_failure(self, scenario_id: UUID, error: str) -> SimulationScenarioRecord:
        updated = self._scenarios.update(
            scenario_id, status=ScenarioStatus.FAILED, error=error
        )
        if updated is None:
            raise LookupError(f"Scenario {scenario_id} not found")
        return updated
