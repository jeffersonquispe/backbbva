from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from uuid import UUID

from src.application.dtos.metrics_dtos import (
    HistogramBucket,
    MetricsRange,
    MetricsWarning,
)


# --- RecordWorkflowStepMetrics (R8) -------------------------------------------


@dataclass
class RecordWorkflowStepMetricsInput:
    alert_id: UUID
    workflow_execution_id: UUID
    # LLM step name -> the model it ran with (config default or a test
    # run's model override). Steps absent here are not LLM steps.
    step_models: dict[str, str] = field(default_factory=dict)


@dataclass
class RecordWorkflowStepMetricsOutput:
    # Step executions counted by this call.
    recorded: int = 0
    # Already counted by an earlier call (retry / redelivery) - skipped.
    already_recorded: int = 0
    # Still RUNNING/PENDING (e.g. a crashed attempt) - not counted.
    not_finished: int = 0


# --- GetTechnicalMetrics (A2, GET /metrics/technical) --------------------------
# Input is metrics_dtos.MetricsQueryInput; on top of the alert filters
# (metrics_filters.FILTER_DIMENSIONS) it accepts TECHNICAL_EXTRA_FILTERS.
# Counts and sums only - averages/rates are left to the client, like the
# other /metrics endpoints (numerator and denominator are both here).

# step_name applies to workflow_step / llm_call / research_call, model to
# llm_call only (ignored by the data types that lack the dimension).
TECHNICAL_EXTRA_FILTERS: tuple[str, ...] = ("step_name", "model")


@dataclass
class DurationStats:
    count: int = 0
    sum_seconds: float = 0.0
    histogram: list[HistogramBucket] = field(default_factory=list)


@dataclass
class WorkflowStepStats:
    # step_name is "" on the all-steps total.
    step_name: str = ""
    executions: int = 0
    succeeded: int = 0
    failed: int = 0
    # Re-executions (adversarial feedback loops, Celery retries).
    retries: int = 0
    duration: DurationStats = field(default_factory=DurationStats)


@dataclass
class LLMCallStats:
    # model is "" on the all-models total.
    model: str = ""
    # LLM step executions (one ReAct step may issue several requests).
    calls: int = 0
    errors: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    latency: DurationStats = field(default_factory=DurationStats)


@dataclass
class ResearchCallStats:
    # source is "" on the all-sources total (vector_store, history_pandas).
    source: str = ""
    calls: int = 0
    ok: int = 0
    failed: int = 0
    timeout: int = 0


@dataclass
class EvaluationStats:
    # Alerts with a valid judge verdict - the denominator of both KPIs.
    evaluated: int = 0
    hallucinations: int = 0
    data_use_correct: int = 0
    # Judge answers that could not be parsed (not in `evaluated`).
    invalid: int = 0


@dataclass
class TechnicalHourSlot:
    hour: int
    step_executions: int = 0
    step_failed: int = 0
    step_duration_sum_seconds: float = 0.0
    step_duration_count: int = 0
    llm_calls: int = 0
    llm_errors: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    research_calls: int = 0
    research_failed: int = 0
    research_timeout: int = 0


@dataclass
class TechnicalPeriod:
    """One planned rollup read plus its headline technical numbers."""

    level: str
    period: str
    period_start: date
    period_end: date
    hours: list[int]
    partial: bool
    # maturing (< 4 days) | may_vary (< 6 months) | stable
    maturation: str
    step_executions: int = 0
    step_failed: int = 0
    llm_calls: int = 0
    llm_errors: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    research_calls: int = 0
    evaluated: int = 0
    hallucinations: int = 0
    data_use_correct: int = 0


@dataclass
class TechnicalMetricsOutput:
    range: MetricsRange
    periods: list[TechnicalPeriod]
    warnings: list[MetricsWarning]
    workflow_steps: WorkflowStepStats
    workflow_steps_by_step: list[WorkflowStepStats]
    llm_calls: LLMCallStats
    llm_calls_by_model: list[LLMCallStats]
    research_calls: ResearchCallStats
    research_calls_by_source: list[ResearchCallStats]
    evaluations: EvaluationStats
    hourly_profile: list[TechnicalHourSlot]
