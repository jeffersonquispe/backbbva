from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from src.application.ports.simulation_scenario_port import (
    GeneratorKind,
    OutputMode,
    ScenarioStatus,
)

# --- Event simulation (scenarios) -------------------------------------------


class RateIntervalSchema(BaseModel):
    start_offset_seconds: int = Field(..., ge=0)
    end_offset_seconds: int = Field(..., gt=0)
    events_per_minute: float = Field(..., ge=0)


class FieldGeneratorSchema(BaseModel):
    kind: GeneratorKind
    value: Any = None
    weights: dict[str, float] | None = None
    params: dict[str, float] | None = None
    system_prompt: str | None = None
    user_prompt_template: str | None = None
    model: str | None = None
    temperature: float = 0.0
    seed_dataset_name: str | None = None
    seed_field: str | None = None


class CreateSimulationScenarioRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    output_mode: OutputMode
    rate_schedule: list[RateIntervalSchema] = Field(..., min_length=1)
    field_specs: dict[str, FieldGeneratorSchema] | None = Field(
        default=None, min_length=1
    )
    target_dataset_name: str | None = None
    created_by: str | None = None


class UpdateSimulationScenarioRequest(BaseModel):
    name: str | None = None
    rate_schedule: list[RateIntervalSchema] | None = None
    field_specs: dict[str, FieldGeneratorSchema] | None = None
    target_dataset_name: str | None = None


class SimulationScenarioResponse(BaseModel):
    id: UUID
    name: str
    status: ScenarioStatus
    output_mode: OutputMode
    rate_schedule: list[RateIntervalSchema]
    field_specs: dict[str, FieldGeneratorSchema]
    target_dataset_name: str | None
    created_by: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    events_emitted: int
    last_tick_offset_seconds: int
    error: str | None


class SimulationStatusResponse(BaseModel):
    scenario_id: UUID
    status: ScenarioStatus
    events_emitted: int
    last_tick_offset_seconds: int
    error: str | None


class SeedSimulationFromDatasetRequest(BaseModel):
    dataset_name: str = Field(..., min_length=1)
