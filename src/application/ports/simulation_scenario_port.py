from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID


class ScenarioStatus(StrEnum):
    DRAFT = "DRAFT"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class OutputMode(StrEnum):
    # Appends generated rows to an aria-api Dataset (via EventSink) - for
    # later batch Test Runs, no live pipeline traffic.
    DATASET = "DATASET"
    # Dispatches each generated event straight into aria-api's real
    # alert-review pipeline (via AlertDispatchGateway) - simulates live
    # traffic hitting the platform.
    LIVE_PIPELINE = "LIVE_PIPELINE"


class GeneratorKind(StrEnum):
    CONSTANT = "CONSTANT"
    CATEGORICAL = "CATEGORICAL"
    UNIFORM = "UNIFORM"
    NORMAL = "NORMAL"
    LOGNORMAL = "LOGNORMAL"
    POISSON = "POISSON"
    # Free-text via a single-shot LLM call, prompt built from already
    # {variable}-substituted fields of the same event (see
    # application/use_cases/event_simulation/field_generation.py's
    # substitute_variables reuse).
    TEMPLATE_LLM = "TEMPLATE_LLM"
    # Pulls one real row from an existing dataset (via DatasetReaderGateway)
    # and asks the LLM to rewrite/vary one of its fields - "recrear campos"
    # from a real seed example instead of inventing one from scratch.
    SEED_RECREATION = "SEED_RECREATION"


@dataclass
class FieldGenerator:
    kind: GeneratorKind
    # CONSTANT
    value: Any = None
    # CATEGORICAL: {value: weight}, weights need not sum to 1 (normalized
    # at draw time)
    weights: dict[str, float] | None = None
    # UNIFORM/NORMAL/LOGNORMAL/POISSON, meaning depends on kind:
    #   UNIFORM: {"low": ..., "high": ...}
    #   NORMAL/LOGNORMAL: {"mu": ..., "sigma": ...}
    #   POISSON: {"lambda": ...}
    params: dict[str, float] | None = None
    # TEMPLATE_LLM / SEED_RECREATION
    system_prompt: str | None = None
    # {field} placeholders resolved against the event's other already-generated
    # fields, same substitute_variables helper alert_review_workflow.py uses.
    user_prompt_template: str | None = None
    model: str | None = None
    temperature: float = 0.0
    # SEED_RECREATION only
    seed_dataset_name: str | None = None
    seed_field: str | None = None


@dataclass
class RateInterval:
    """One leg of a scenario's arrival-rate curve, relative to the
    scenario's own start (not wall-clock time) - "minute 0-10: 5 ev/min,
    minute 10-15: 50 ev/min" for a burst test."""

    start_offset_seconds: int
    end_offset_seconds: int
    events_per_minute: float


@dataclass
class SimulationScenarioRecord:
    id: UUID
    name: str
    status: ScenarioStatus
    output_mode: OutputMode
    rate_schedule: list[RateInterval]
    field_specs: dict[str, FieldGenerator]
    created_at: datetime
    updated_at: datetime
    # Required when output_mode == DATASET (target of EventSink.write_batch).
    target_dataset_name: str | None = None
    created_by: str | None = None
    started_at: datetime | None = None
    events_emitted: int = 0
    last_tick_offset_seconds: int = 0
    error: str | None = None


class SimulationScenarioRepository(Protocol):
    def create(
        self, scenario: SimulationScenarioRecord
    ) -> SimulationScenarioRecord: ...

    def get(self, scenario_id: UUID) -> SimulationScenarioRecord | None: ...

    def list(
        self, status: ScenarioStatus | None = None
    ) -> list[SimulationScenarioRecord]: ...

    def update(
        self,
        scenario_id: UUID,
        **changes: Any,
    ) -> SimulationScenarioRecord | None: ...

    def delete(self, scenario_id: UUID) -> None: ...
