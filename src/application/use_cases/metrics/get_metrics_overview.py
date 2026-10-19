"""GetMetricsOverview (A2): GET /metrics/overview, the /dashboard KPIs -
volume, funnel by status, false positives / undetected fraud (mark x
fraud_label, pending excluded), amounts, distributions per dimension,
resolution time, 0-23 h profile and per-period maturation."""

from __future__ import annotations

from src.application.dtos.metrics_dtos import MetricsOverviewOutput, MetricsQueryInput
from src.application.ports.clock_port import Clock
from src.application.ports.metrics_rollup_port import (
    ALERT_DIMENSIONS,
    MetricsRollupRepository,
)
from src.application.ports.operational_settings_port import (
    OperationalSettingsRepository,
)
from src.application.runtime_defaults import resolve_clock
from src.application.use_cases.metrics import alert_metrics_reader as reader
from src.domain.alerts.entities import (
    AlertStatus,
)


class GetMetricsOverview:
    def __init__(
        self,
        rollup_repository: MetricsRollupRepository,
        timezone_name: str,
        clock: Clock | None = None,
        operational_settings_repository: OperationalSettingsRepository | None = None,
    ) -> None:
        self._rollups = rollup_repository
        self._timezone_name = timezone_name
        self._clock = resolve_clock(clock)
        self._operational_settings = operational_settings_repository

    def execute(self, input: MetricsQueryInput) -> MetricsOverviewOutput:
        """Raises ValueError for a naive/inverted range or unknown filter."""
        read = reader.read_alert_rollups(
            self._rollups,
            input,
            self._clock.now(),
            self._timezone_name,
            self._operational_settings,
        )
        rows = read.rows
        distributions = reader.dimension_distributions(rows, ALERT_DIMENSIONS)
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
            distributions=distributions,
            hourly_profile=reader.hourly_profile(rows),
        )
