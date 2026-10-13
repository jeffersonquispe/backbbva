"""Input/Output of GetMetricsOverview (/metrics/overview, /dashboard) and
GetAgentMetrics (/metrics/agent, /monitor). Every number is a sum of
additive rollup measures over the planned periods - counts and sums only;
rates/averages are left to the client (numerator + denominator are both
here)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass
class MetricsQueryInput:
    # [from_, to). to defaults to now, from_ to to - 24 h.
    from_: datetime | None = None
    to: datetime | None = None
    # Dimension name -> accepted values (metrics_filters.FILTER_DIMENSIONS).
    filters: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class MetricsRange:
    from_: datetime
    to: datetime
    timezone: str
    # Distinct schema versions among the alerts read.
    schema_versions: list[str] = field(default_factory=list)


@dataclass
class MetricsPeriod:
    """One planned rollup read plus its own headline numbers (for the
    per-period maturation badges)."""

    level: str
    period: str
    period_start: date
    period_end: date
    hours: list[int]
    partial: bool
    # maturing (< 4 days) | may_vary (< 6 months) | stable
    maturation: str
    alerts: int = 0
    amount_sum: float = 0.0
    decided: int = 0
    false_positives: int = 0
    undetected_fraud: int = 0
    reviewed: int = 0


@dataclass
class MetricsWarning:
    # partial_period | schema_changed | fraud_label_maturing
    code: str
    message: str
    periods: list[str] = field(default_factory=list)


@dataclass
class HistogramBucket:
    bucket: str
    # Exclusive upper bound in seconds; None = unbounded.
    upper_bound_seconds: float | None
    count: int


@dataclass
class ResolutionTimeStats:
    count: int = 0
    sum_seconds: float = 0.0
    # Resolved in < 5 min (rt_lt_1m + rt_1_5m) - exact.
    within_sla_count: int = 0
    histogram: list[HistogramBucket] = field(default_factory=list)


@dataclass
class FraudQualityStats:
    """mark x fraud_label confusion matrix. Alerts whose mark is pending
    are excluded from every cell (decision D8)."""

    decided: int = 0
    pending: int = 0
    true_positives: int = 0
    true_negatives: int = 0
    false_positives: int = 0
    undetected_fraud: int = 0
    true_positive_amount_sum: float = 0.0
    false_positive_amount_sum: float = 0.0
    undetected_fraud_amount_sum: float = 0.0
    reviewed: int = 0
    reviewed_changed: int = 0
    reviewed_confirmed: int = 0
    review_events: int = 0
    # fraud_reviewed_at - marked_at.
    maturation_histogram: list[HistogramBucket] = field(default_factory=list)


@dataclass
class DimensionBucket:
    value: str
    alerts: int = 0
    amount_sum: float = 0.0
    amount_count: int = 0
    decided: int = 0
    false_positives: int = 0
    undetected_fraud: int = 0


@dataclass
class HourlyProfileSlot:
    hour: int
    alerts: int = 0
    amount_sum: float = 0.0
    resolution_time_count: int = 0
    resolution_time_sum_seconds: float = 0.0
    within_sla_count: int = 0


@dataclass
class MetricsTotals:
    alerts: int = 0
    amount_sum: float = 0.0
    amount_count: int = 0


@dataclass
class MetricsOverviewOutput:
    range: MetricsRange
    periods: list[MetricsPeriod]
    warnings: list[MetricsWarning]
    totals: MetricsTotals
    funnel_by_status: list[DimensionBucket]
    fraud_quality: FraudQualityStats
    resolution_time: ResolutionTimeStats
    # Dimension name (every rollup dimension) -> buckets, largest first.
    distributions: dict[str, list[DimensionBucket]]
    hourly_profile: list[HourlyProfileSlot]


@dataclass
class ResolutionMethodStats:
    # aria | analyst | voicebot | bidi | unknown (no decision channel yet)
    resolution_method: str
    alerts: int
    fraud_marks: int
    no_fraud_marks: int
    fraud_quality: FraudQualityStats
    resolution_time: ResolutionTimeStats


@dataclass
class RecommendationAcceptance:
    available: bool
    accepted: int | None
    ignored: int | None
    reason: str


@dataclass
class AgentMetricsOutput:
    range: MetricsRange
    periods: list[MetricsPeriod]
    warnings: list[MetricsWarning]
    totals: MetricsTotals
    by_resolution_method: list[ResolutionMethodStats]
    fraud_quality: FraudQualityStats
    resolution_time: ResolutionTimeStats
    hourly_profile: list[HourlyProfileSlot]
    recommendations: RecommendationAcceptance
