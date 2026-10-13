from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel

from src.infrastructure.entrypoint.api.schemas.metrics import (
    HistogramBucketSchema,
    MetricsRangeSchema,
    MetricsWarningSchema,
)

# --- Metrics (A2): GET /metrics/technical ----------------------------------
# Mirrors application/dtos/technical_metrics_dtos.py. Sums only: avg
# latency = duration.sum_seconds / duration.count, hallucination % =
# evaluations.hallucinations / evaluations.evaluated, etc.


class DurationStatsSchema(BaseModel):
    count: int
    sum_seconds: float
    histogram: list[HistogramBucketSchema]


class WorkflowStepStatsSchema(BaseModel):
    step_name: str
    executions: int
    succeeded: int
    failed: int
    retries: int
    duration: DurationStatsSchema


class LLMCallStatsSchema(BaseModel):
    model: str
    calls: int
    errors: int
    input_tokens: int
    output_tokens: int
    latency: DurationStatsSchema


class ResearchCallStatsSchema(BaseModel):
    source: str
    calls: int
    ok: int
    failed: int
    timeout: int


class EvaluationStatsSchema(BaseModel):
    evaluated: int
    hallucinations: int
    data_use_correct: int
    invalid: int


class TechnicalHourSlotSchema(BaseModel):
    hour: int
    step_executions: int
    step_failed: int
    step_duration_sum_seconds: float
    step_duration_count: int
    llm_calls: int
    llm_errors: int
    input_tokens: int
    output_tokens: int
    research_calls: int
    research_failed: int
    research_timeout: int


class TechnicalPeriodSchema(BaseModel):
    level: Literal["day", "month", "year"]
    period: str
    period_start: date
    period_end: date
    hours: list[int]
    partial: bool
    maturation: Literal["maturing", "may_vary", "stable"]
    step_executions: int
    step_failed: int
    llm_calls: int
    llm_errors: int
    input_tokens: int
    output_tokens: int
    research_calls: int
    evaluated: int
    hallucinations: int
    data_use_correct: int


class TechnicalMetricsResponse(BaseModel):
    range: MetricsRangeSchema
    periods: list[TechnicalPeriodSchema]
    warnings: list[MetricsWarningSchema]
    workflow_steps: WorkflowStepStatsSchema
    workflow_steps_by_step: list[WorkflowStepStatsSchema]
    llm_calls: LLMCallStatsSchema
    llm_calls_by_model: list[LLMCallStatsSchema]
    research_calls: ResearchCallStatsSchema
    research_calls_by_source: list[ResearchCallStatsSchema]
    evaluations: EvaluationStatsSchema
    hourly_profile: list[TechnicalHourSlotSchema]
