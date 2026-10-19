"""GetAgentMetrics (A2): GET /metrics/agent, the /monitor KPIs - who
resolves (ARIA vs analyst vs voicebot vs bidi), each one's decision
quality (mark x fraud_label) and resolution-time histogram, plus the
0-23 h profile and per-period maturation.

"% analyst recommendations accepted" is NOT derivable: ARIA's
recommendation to the analyst is not part of the alert metrics snapshot,
so no rollup holds it - the response says so (available = false)."""

from __future__ import annotations

from src.application.dtos.metrics_dtos import (
    AgentMetricsOutput,
    MetricsQueryInput,
    RecommendationAcceptance,
    ResolutionMethodStats,
)
from src.application.ports.clock_port import Clock
from src.application.ports.metrics_rollup_port import MetricsRollupRepository
from src.application.ports.operational_settings_port import (
    OperationalSettingsRepository,
)
from src.application.runtime_defaults import resolve_clock
from src.application.use_cases.metrics import alert_metrics_reader as reader
from src.domain.alerts.entities import (
    AlertResolutionMethod,
    Mark,
)

RESOLUTION_METHODS = [m.value for m in AlertResolutionMethod] + ["unknown"]

RECOMMENDATIONS_UNAVAILABLE = (
    "Not derivable from the metrics rollups: ARIA's recommendation to the "
    "analyst is not recorded in the alert metrics snapshot, so accepted vs "
    "ignored recommendations are not counted yet."
)


class GetAgentMetrics:
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

    def execute(self, input: MetricsQueryInput) -> AgentMetricsOutput:
        """Raises ValueError for a naive/inverted range or unknown filter."""
        read = reader.read_alert_rollups(
            self._rollups,
            input,
            self._clock.now(),
            self._timezone_name,
            self._operational_settings,
        )
        rows = read.rows
        groups: dict[str, list[reader.PlannedRow]] = {m: [] for m in RESOLUTION_METHODS}
        for r in rows:
            groups.setdefault(r.dimension("resolution_method"), []).append(r)
        by_method: list[ResolutionMethodStats] = []
        for method, group in groups.items():
            quality = reader.fraud_quality(group)
            by_method.append(
                ResolutionMethodStats(
                    resolution_method=method,
                    alerts=reader.totals(group).alerts,
                    fraud_marks=reader.count_where(group, "mark", Mark.FRAUD.value),
                    no_fraud_marks=reader.count_where(
                        group, "mark", Mark.NO_FRAUD.value
                    ),
                    fraud_quality=quality,
                    resolution_time=reader.resolution_time(group),
                )
            )
        return AgentMetricsOutput(
            range=read.range,
            periods=reader.periods(read),
            warnings=reader.warnings(read),
            totals=reader.totals(rows),
            by_resolution_method=by_method,
            fraud_quality=reader.fraud_quality(rows),
            resolution_time=reader.resolution_time(rows),
            hourly_profile=reader.hourly_profile(rows),
            recommendations=RecommendationAcceptance(
                available=False,
                accepted=None,
                ignored=None,
                reason=RECOMMENDATIONS_UNAVAILABLE,
            ),
        )
