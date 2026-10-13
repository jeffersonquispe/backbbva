from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# --- Metrics (A2): GET /metrics/overview, GET /metrics/agent ----------------
# Mirrors application/dtos/metrics_dtos.py. Every number is a sum of additive
# rollup measures; rates/averages are numerator / denominator on the client.


class MetricsRangeSchema(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_: datetime = Field(alias="from")
    to: datetime
    timezone: str
    schema_versions: list[str] = Field(default_factory=list)


class MetricsPeriodSchema(BaseModel):
    level: Literal["day", "month", "year"]
    period: str
    period_start: date
    period_end: date
    hours: list[int]
    partial: bool
    maturation: Literal["maturing", "may_vary", "stable"]
    alerts: int
    amount_sum: float
    decided: int
    false_positives: int
    undetected_fraud: int
    reviewed: int


class MetricsWarningSchema(BaseModel):
    code: Literal["partial_period", "schema_changed", "fraud_label_maturing"]
    message: str
    periods: list[str] = Field(default_factory=list)


class HistogramBucketSchema(BaseModel):
    bucket: str
    upper_bound_seconds: float | None
    count: int


class ResolutionTimeStatsSchema(BaseModel):
    count: int
    sum_seconds: float
    within_sla_count: int
    histogram: list[HistogramBucketSchema]


class FraudQualityStatsSchema(BaseModel):
    decided: int
    pending: int
    true_positives: int
    true_negatives: int
    false_positives: int
    undetected_fraud: int
    true_positive_amount_sum: float
    false_positive_amount_sum: float
    undetected_fraud_amount_sum: float
    reviewed: int
    reviewed_changed: int
    reviewed_confirmed: int
    review_events: int
    maturation_histogram: list[HistogramBucketSchema]


class DimensionBucketSchema(BaseModel):
    value: str
    alerts: int
    amount_sum: float
    amount_count: int
    decided: int
    false_positives: int
    undetected_fraud: int


class HourlyProfileSlotSchema(BaseModel):
    hour: int
    alerts: int
    amount_sum: float
    resolution_time_count: int
    resolution_time_sum_seconds: float
    within_sla_count: int


class MetricsTotalsSchema(BaseModel):
    alerts: int
    amount_sum: float
    amount_count: int


class MetricsOverviewResponse(BaseModel):
    range: MetricsRangeSchema
    periods: list[MetricsPeriodSchema]
    warnings: list[MetricsWarningSchema]
    totals: MetricsTotalsSchema
    funnel_by_status: list[DimensionBucketSchema]
    fraud_quality: FraudQualityStatsSchema
    resolution_time: ResolutionTimeStatsSchema
    distributions: dict[str, list[DimensionBucketSchema]]
    hourly_profile: list[HourlyProfileSlotSchema]


class ResolutionMethodStatsSchema(BaseModel):
    resolution_method: Literal["aria", "analyst", "voicebot", "bidi", "unknown"]
    alerts: int
    fraud_marks: int
    no_fraud_marks: int
    fraud_quality: FraudQualityStatsSchema
    resolution_time: ResolutionTimeStatsSchema


class RecommendationAcceptanceSchema(BaseModel):
    available: bool
    accepted: int | None
    ignored: int | None
    reason: str


class AgentMetricsResponse(BaseModel):
    range: MetricsRangeSchema
    periods: list[MetricsPeriodSchema]
    warnings: list[MetricsWarningSchema]
    totals: MetricsTotalsSchema
    by_resolution_method: list[ResolutionMethodStatsSchema]
    fraud_quality: FraudQualityStatsSchema
    resolution_time: ResolutionTimeStatsSchema
    hourly_profile: list[HourlyProfileSlotSchema]
    recommendations: RecommendationAcceptanceSchema
