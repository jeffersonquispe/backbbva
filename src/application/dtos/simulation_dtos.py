from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from src.application.ports.simulation_scenario_port import (
    FieldGenerator,
    OutputMode,
    RateInterval,
    ScenarioStatus,
    SimulationScenarioRecord,
)


@dataclass
class CreateSimulationScenarioInput:
    name: str
    output_mode: OutputMode
    rate_schedule: list[RateInterval]
    field_specs: dict[str, FieldGenerator] | None = None
    target_dataset_name: str | None = None
    created_by: str | None = None


@dataclass
class SeedSimulationFromDatasetInput:
    dataset_name: str


@dataclass
class UpdateSimulationScenarioInput:
    scenario_id: UUID
    name: str | None = None
    rate_schedule: list[RateInterval] | None = None
    field_specs: dict[str, FieldGenerator] | None = None
    target_dataset_name: str | None = None


@dataclass
class GenerateEventBatchInput:
    scenario: SimulationScenarioRecord
    # Inclusive-exclusive window, in seconds since the scenario's own
    # started_at - not wall-clock time, so a paused-then-resumed scenario
    # doesn't lose/duplicate its rate curve's progress.
    window_start_seconds: int
    window_end_seconds: int
    max_events: int
    seed: int | None = None


@dataclass
class GenerateEventBatchOutput:
    rows: list[dict]
    events_generated: int
    # True if the rate schedule has no more intervals past window_end_seconds
    # - the tick loop uses this to flip the scenario to COMPLETED instead of
    # rescheduling another tick.
    schedule_exhausted: bool


@dataclass
class SimulationStatusOutput:
    scenario_id: UUID
    status: ScenarioStatus
    events_emitted: int
    last_tick_offset_seconds: int
    error: str | None
