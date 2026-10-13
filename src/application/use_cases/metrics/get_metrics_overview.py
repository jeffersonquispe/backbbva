"""GetMetricsOverview (A2): GET /metrics/overview, the /dashboard KPIs -
volume, funnel by status, false positives / undetected fraud (mark x
fraud_label, pending excluded), amounts, distributions per dimension,
resolution time, 0-23 h profile and per-period maturation."""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from src.application.dtos.metrics_dtos import MetricsOverviewOutput, MetricsQueryInput
from src.application.ports.alert_port import AlertStatus
from src.application.ports.metrics_rollup_port import (
    ALERT_DIMENSIONS,
    MetricsRollupRepository,
)
from src.application.use_cases.metrics import alert_metrics_reader as reader


class GetMetricsOverview:
    def __init__(
        self,
        rollup_repository: MetricsRollupRepository,
        timezone_name: str,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._rollups = rollup_repository
        self._timezone_name = timezone_name
        self._clock = clock

    def execute(self, input: MetricsQueryInput) -> MetricsOverviewOutput:
        """Raises ValueError for a naive/inverted range or unknown filter."""
        read = reader.read_alert_rollups(
            self._rollups, input, self._clock(), self._timezone_name
        )
        rows = read.rows
        return MetricsOverviewOutput(
            range=read.range,
            periods=reader.periods(read),
            warnings=reader.warnings(read),
            totals=reader.totals(rows),
            funnel_by_status=reader.dimension_buckets(
                rows, "status", order=[s.value for s in AlertStatus]
            ),
            fraud_quality=reader.fraud_quality(rows),
            resolution_time=reader.resolution_time(rows),
            distributions={
                name: reader.dimension_buckets(rows, name) for name in ALERT_DIMENSIONS
            },
            hourly_profile=reader.hourly_profile(rows),
        )
