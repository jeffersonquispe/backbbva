"""GetTechnicalMetrics (A2, GET /metrics/technical, /monitor): workflow
steps, LLM calls, research calls and reasoning evaluations for a time range,
summed from the rollups the range planner selects.

Same contract as /metrics/overview and /metrics/agent (MetricsQueryInput,
range defaults, MetricsRange, MetricsWarning): only sums of stored additive
measures - the client divides (avg latency = sum_seconds / count,
hallucination % = hallucinations / evaluated). The range is over the
alerts' arrival, the rollups' bucket."""

from __future__ import annotations

from collections import defaultdict

from src.application.dtos.metrics_dtos import (
    HistogramBucket,
    MetricsQueryInput,
    MetricsRange,
    MetricsWarning,
)
from src.application.dtos.technical_metrics_dtos import (
    TECHNICAL_EXTRA_FILTERS,
    DurationStats,
    EvaluationStats,
    LLMCallStats,
    ResearchCallStats,
    TechnicalHourSlot,
    TechnicalMetricsOutput,
    TechnicalPeriod,
    WorkflowStepStats,
)
from src.application.ports.clock_port import Clock
from src.application.ports.metrics_rollup_port import (
    UNKNOWN_DIMENSION,
    MetricsDataType,
    MetricsRollupRepository,
    RollupLevel,
    RollupRow,
)
from src.application.runtime_defaults import resolve_clock
from src.application.use_cases.metrics import technical_rollup_contribution as m
from src.application.use_cases.metrics.alert_metrics_reader import DEFAULT_RANGE
from src.application.use_cases.metrics.metrics_filters import normalize_filters
from src.application.use_cases.metrics.range_planner import PlannedRead, plan

Measures = dict[str, float]
Rows = list[tuple[RollupRow, PlannedRead]]

# Which of TECHNICAL_EXTRA_FILTERS each data type has as a dimension (the
# alert filters apply to all of them).
_EXTRA_DIMENSIONS: dict[MetricsDataType, frozenset[str]] = {
    MetricsDataType.WORKFLOW_STEP: frozenset({"step_name"}),
    MetricsDataType.LLM_CALL: frozenset({"step_name", "model"}),
    MetricsDataType.RESEARCH_CALL: frozenset({"step_name"}),
    MetricsDataType.EVALUATION: frozenset(),
}


def normalize_technical_filters(
    filters: dict[str, list[str]] | None,
) -> dict[str, list[str]]:
    """Alert filters as metrics_filters.normalize_filters, plus step_name /
    model. Raises ValidationError for any other name."""
    filters = dict(filters or {})
    extra = {
        name: filters.pop(name) for name in TECHNICAL_EXTRA_FILTERS if name in filters
    }
    normalized = normalize_filters(filters)
    for name, values in extra.items():
        kept = [str(v).strip() for v in values or [] if str(v).strip()]
        if kept:
            normalized[name] = kept
    return normalized


class GetTechnicalMetrics:
    def __init__(
        self,
        rollup_repository: MetricsRollupRepository,
        timezone_name: str,
        clock: Clock | None = None,
    ) -> None:
        self._rollups = rollup_repository
        self._timezone_name = timezone_name
        self._clock = resolve_clock(clock)

    def execute(self, input: MetricsQueryInput) -> TechnicalMetricsOutput:
        """Raises ValidationError for an invalid range or unknown filter."""
        now = self._clock.now()
        to = input.to or now
        from_ = input.from_ or (to - DEFAULT_RANGE)
        filters = normalize_technical_filters(input.filters)
        reads = plan(from_, to, now, self._timezone_name)
        rows = {
            data_type: self._read(data_type, reads, filters)
            for data_type in _EXTRA_DIMENSIONS
        }
        steps = rows[MetricsDataType.WORKFLOW_STEP]
        llm = rows[MetricsDataType.LLM_CALL]
        research = rows[MetricsDataType.RESEARCH_CALL]
        evaluations = rows[MetricsDataType.EVALUATION]
        versions = sorted(
            {
                row.key.dimension("schema_version") or UNKNOWN_DIMENSION
                for typed in rows.values()
                for row, _ in typed
            }
        )
        return TechnicalMetricsOutput(
            range=MetricsRange(
                from_=from_,
                to=to,
                timezone=self._timezone_name,
                schema_versions=versions,
            ),
            periods=_periods(reads, rows),
            warnings=_warnings(reads, versions),
            workflow_steps=_step_stats(_sum(steps)),
            workflow_steps_by_step=[
                _step_stats(measures, name)
                for name, measures in _group(steps, "step_name")
            ],
            llm_calls=_llm_stats(_sum(llm)),
            llm_calls_by_model=[
                _llm_stats(measures, name) for name, measures in _group(llm, "model")
            ],
            research_calls=_research_stats(_sum(research)),
            research_calls_by_source=[
                _research_stats(measures, name)
                for name, measures in _group(research, "source")
            ],
            evaluations=_evaluation_stats(_sum(evaluations)),
            hourly_profile=_hourly(rows),
        )

    def _read(
        self,
        data_type: MetricsDataType,
        reads: list[PlannedRead],
        filters: dict[str, list[str]],
    ) -> Rows:
        """Each matching row paired with the planned read it belongs to
        (whose hours are the slots to sum). A filter on a dimension this
        type lacks (model on workflow_step) is not applied to it."""
        applicable = {
            name: values
            for name, values in filters.items()
            if name not in TECHNICAL_EXTRA_FILTERS
            or name in _EXTRA_DIMENSIONS[data_type]
        }
        by_level: dict[str, dict[str, PlannedRead]] = defaultdict(dict)
        for read in reads:
            by_level[read.level.value][read.period] = read
        result: Rows = []
        for level, periods in by_level.items():
            for row in self._rollups.query(
                data_type, RollupLevel(level), list(periods), applicable or None
            ):
                planned = periods.get(row.key.period)
                if planned is not None:
                    result.append((row, planned))
        return result


# --- folding -----------------------------------------------------------------


def _int(value: float) -> int:
    return int(round(value))


def _row_measures(row: RollupRow, read: PlannedRead) -> Measures:
    return {name: row.total(name, read.hours) for name in row.measures}


def _add(target: Measures, source: Measures) -> None:
    for name, value in source.items():
        target[name] = target.get(name, 0) + value


def _sum(rows: Rows) -> Measures:
    total: Measures = {}
    for row, read in rows:
        _add(total, _row_measures(row, read))
    return total


def _group(rows: Rows, dimension: str) -> list[tuple[str, Measures]]:
    groups: dict[str, Measures] = defaultdict(dict)
    for row, read in rows:
        _add(
            groups[row.key.dimension(dimension) or UNKNOWN_DIMENSION],
            _row_measures(row, read),
        )
    return sorted(groups.items())


def _duration(measures: Measures) -> DurationStats:
    return DurationStats(
        count=_int(measures.get(m.DURATION_COUNT, 0)),
        sum_seconds=measures.get(m.DURATION_SUM_SECONDS, 0.0),
        histogram=[
            HistogramBucket(
                bucket=name,
                upper_bound_seconds=upper,
                count=_int(measures.get(name, 0)),
            )
            for name, upper in m.DURATION_BUCKETS
        ],
    )


def _step_stats(measures: Measures, step_name: str = "") -> WorkflowStepStats:
    return WorkflowStepStats(
        step_name=step_name,
        executions=_int(measures.get(m.COUNT, 0)),
        succeeded=_int(measures.get(m.SUCCEEDED_COUNT, 0)),
        failed=_int(measures.get(m.FAILED_COUNT, 0)),
        retries=_int(measures.get(m.RETRY_COUNT, 0)),
        duration=_duration(measures),
    )


def _llm_stats(measures: Measures, model: str = "") -> LLMCallStats:
    return LLMCallStats(
        model=model,
        calls=_int(measures.get(m.COUNT, 0)),
        errors=_int(measures.get(m.ERROR_COUNT, 0)),
        input_tokens=_int(measures.get(m.INPUT_TOKENS, 0)),
        output_tokens=_int(measures.get(m.OUTPUT_TOKENS, 0)),
        latency=_duration(measures),
    )


def _research_stats(measures: Measures, source: str = "") -> ResearchCallStats:
    return ResearchCallStats(
        source=source,
        calls=_int(measures.get(m.COUNT, 0)),
        ok=_int(measures.get(m.OK_COUNT, 0)),
        failed=_int(measures.get(m.FAILED_COUNT, 0)),
        timeout=_int(measures.get(m.TIMEOUT_COUNT, 0)),
    )


def _evaluation_stats(measures: Measures) -> EvaluationStats:
    return EvaluationStats(
        evaluated=_int(measures.get(m.COUNT, 0)),
        hallucinations=_int(measures.get(m.HALLUCINATION_COUNT, 0)),
        data_use_correct=_int(measures.get(m.DATA_USE_CORRECT_COUNT, 0)),
        invalid=_int(measures.get(m.INVALID_COUNT, 0)),
    )


def _slot(rows: Rows, measure: str, hour: int) -> float:
    total = 0.0
    for row, read in rows:
        if hour in read.hours:
            slots = row.measures.get(measure)
            if slots:
                total += slots[hour]
    return total


def _hourly(rows: dict[MetricsDataType, Rows]) -> list[TechnicalHourSlot]:
    steps = rows[MetricsDataType.WORKFLOW_STEP]
    llm = rows[MetricsDataType.LLM_CALL]
    research = rows[MetricsDataType.RESEARCH_CALL]
    return [
        TechnicalHourSlot(
            hour=hour,
            step_executions=_int(_slot(steps, m.COUNT, hour)),
            step_failed=_int(_slot(steps, m.FAILED_COUNT, hour)),
            step_duration_sum_seconds=_slot(steps, m.DURATION_SUM_SECONDS, hour),
            step_duration_count=_int(_slot(steps, m.DURATION_COUNT, hour)),
            llm_calls=_int(_slot(llm, m.COUNT, hour)),
            llm_errors=_int(_slot(llm, m.ERROR_COUNT, hour)),
            input_tokens=_int(_slot(llm, m.INPUT_TOKENS, hour)),
            output_tokens=_int(_slot(llm, m.OUTPUT_TOKENS, hour)),
            research_calls=_int(_slot(research, m.COUNT, hour)),
            research_failed=_int(_slot(research, m.FAILED_COUNT, hour)),
            research_timeout=_int(_slot(research, m.TIMEOUT_COUNT, hour)),
        )
        for hour in range(24)
    ]


def _periods(
    reads: list[PlannedRead], rows: dict[MetricsDataType, Rows]
) -> list[TechnicalPeriod]:
    def per_read(data_type: MetricsDataType) -> dict[tuple[str, str], Measures]:
        totals: dict[tuple[str, str], Measures] = defaultdict(dict)
        for row, read in rows[data_type]:
            _add(totals[(read.level.value, read.period)], _row_measures(row, read))
        return totals

    steps = per_read(MetricsDataType.WORKFLOW_STEP)
    llm = per_read(MetricsDataType.LLM_CALL)
    research = per_read(MetricsDataType.RESEARCH_CALL)
    evaluations = per_read(MetricsDataType.EVALUATION)
    result: list[TechnicalPeriod] = []
    for read in reads:
        key = (read.level.value, read.period)
        step_measures, llm_measures, research_measures, evaluation_measures = (
            steps.get(key, {}),
            llm.get(key, {}),
            research.get(key, {}),
            evaluations.get(key, {}),
        )
        result.append(
            TechnicalPeriod(
                level=read.level.value,
                period=read.period,
                period_start=read.period_start,
                period_end=read.period_end,
                hours=list(read.hours),
                partial=read.partial,
                maturation=read.maturation.value,
                step_executions=_int(step_measures.get(m.COUNT, 0)),
                step_failed=_int(step_measures.get(m.FAILED_COUNT, 0)),
                llm_calls=_int(llm_measures.get(m.COUNT, 0)),
                llm_errors=_int(llm_measures.get(m.ERROR_COUNT, 0)),
                input_tokens=_int(llm_measures.get(m.INPUT_TOKENS, 0)),
                output_tokens=_int(llm_measures.get(m.OUTPUT_TOKENS, 0)),
                research_calls=_int(research_measures.get(m.COUNT, 0)),
                evaluated=_int(evaluation_measures.get(m.COUNT, 0)),
                hallucinations=_int(evaluation_measures.get(m.HALLUCINATION_COUNT, 0)),
                data_use_correct=_int(
                    evaluation_measures.get(m.DATA_USE_CORRECT_COUNT, 0)
                ),
            )
        )
    return result


def _warnings(reads: list[PlannedRead], versions: list[str]) -> list[MetricsWarning]:
    """Same codes as /metrics/overview and /metrics/agent. No
    fraud_label_maturing: no technical measure depends on fraud_label."""
    result: list[MetricsWarning] = []
    partial = [r.period for r in reads if r.partial]
    if partial:
        result.append(
            MetricsWarning(
                code="partial_period",
                message=(
                    "Older than 90 days the data is only kept per month/year: "
                    "these periods are counted whole and include alerts outside "
                    "the requested range."
                ),
                periods=partial,
            )
        )
    if len(versions) > 1:
        result.append(
            MetricsWarning(
                code="schema_changed",
                message=(
                    "The range spans more than one amount-tier set (versions "
                    + ", ".join(versions)
                    + "): each alert keeps the tier it was classified with on arrival."
                ),
            )
        )
    return result
