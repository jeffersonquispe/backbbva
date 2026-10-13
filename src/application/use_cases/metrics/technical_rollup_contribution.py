"""What one finished workflow step (R8) or one reasoning evaluation (D6)
adds to the technical rollups. Pure functions: no I/O, the timezone is a
parameter.

Technical rows are bucketed like the alert rows - by the alert's arrival
(created_at) in local time, on every live level - so "alerts that arrived
yesterday" means the same set of alerts on every /metrics endpoint. They are
written once per source event (see RecordWorkflowStepMetrics /
EvaluateAlertReasoning and MetricsRollupRepository.apply_once) and never
re-deltaed, which is why they carry TECHNICAL_ALERT_DIMENSIONS (no mark /
fraud_label).

Per step execution record:
- workflow_step  (+ step_name): one execution, its outcome, duration and
  whether it was a re-execution (feedback loop or Celery retry).
- llm_call       (+ step_name, model): one LLM step execution (a ReAct step
  may issue several model requests - the per-request count lives in the
  OTLP spans). Tokens are exactly the step output's input_tokens /
  output_tokens, the same numbers test_runs/token_usage.py sums.
- research_call  (+ step_name, source): each delegated research / vector
  store tool call the step recorded, by outcome ok / failed / timeout.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, tzinfo
from typing import Any

from src.application.ports.metrics_rollup_port import (
    EVALUATION_DIMENSIONS,
    LLM_CALL_DIMENSIONS,
    RESEARCH_CALL_DIMENSIONS,
    TECHNICAL_ALERT_DIMENSIONS,
    UNKNOWN_DIMENSION,
    WORKFLOW_STEP_DIMENSIONS,
    MetricsDataType,
    RollupDelta,
    RollupKey,
)
from src.application.ports.monitoring_port import ResearchCallOutcome
from src.application.use_cases.metrics.alert_rollup_contribution import (
    _bucket,
    _dim,
    _zone,
    live_periods,
)
from src.application.use_cases.test_runs.token_usage import sum_step_tokens
from src.domain.alerts.entities import (
    AlertMetricsSnapshot,
    AlertStatus,
)
from src.domain.workflows.entities import (
    WorkflowStepExecutionRecord,
    WorkflowStepStatus,
)

# --- measure names (all additive) -------------------------------------------

COUNT = "count"
# workflow_step
SUCCEEDED_COUNT = "succeeded_count"
FAILED_COUNT = "failed_count"
RETRY_COUNT = "retry_count"
# workflow_step and llm_call (llm_call: the LLM step's latency)
DURATION_COUNT = "duration_count"
DURATION_SUM_SECONDS = "duration_sum_seconds"
DURATION_BUCKETS: tuple[tuple[str, float | None], ...] = (
    ("dur_lt_1s", 1),
    ("dur_1_5s", 5),
    ("dur_5_15s", 15),
    ("dur_15_30s", 30),
    ("dur_30_60s", 60),
    ("dur_gt_60s", None),
)
# llm_call
ERROR_COUNT = "error_count"
INPUT_TOKENS = "input_tokens"
OUTPUT_TOKENS = "output_tokens"
# research_call
OK_COUNT = "ok_count"
TIMEOUT_COUNT = "timeout_count"
# FAILED_COUNT is shared with workflow_step.
RESEARCH_OUTCOME_MEASURES = {
    ResearchCallOutcome.OK: OK_COUNT,
    ResearchCallOutcome.FAILED: FAILED_COUNT,
    ResearchCallOutcome.TIMEOUT: TIMEOUT_COUNT,
}
# evaluation: COUNT = valid verdicts only; INVALID_COUNT = judge output that
# could not be parsed (kept apart so it never dilutes the rates).
HALLUCINATION_COUNT = "hallucination_count"
DATA_USE_CORRECT_COUNT = "data_use_correct_count"
INVALID_COUNT = "invalid_count"

_TERMINAL_STEP_STATUSES = (WorkflowStepStatus.SUCCEEDED, WorkflowStepStatus.FAILED)


@dataclass(frozen=True)
class TechnicalContribution:
    """One row's worth of increments, before levels/periods are applied."""

    data_type: MetricsDataType
    dimensions: tuple[tuple[str, str], ...]
    measures: dict[str, float] = field(default_factory=dict)


def technical_alert_dimensions(
    snapshot: AlertMetricsSnapshot | None, alert_status: AlertStatus | None = None
) -> tuple[tuple[str, str], ...]:
    """TECHNICAL_ALERT_DIMENSIONS from the alert's metrics snapshot. An
    alert without one (its metrics events failed) still counts, under
    `unknown` - with the alert's own status when known."""
    if snapshot is None:
        return tuple(
            (name, _dim(alert_status) if name == "status" else UNKNOWN_DIMENSION)
            for name in TECHNICAL_ALERT_DIMENSIONS
        )
    return tuple(
        (name, _dim(getattr(snapshot, name))) for name in TECHNICAL_ALERT_DIMENSIONS
    )


def is_finished(step: WorkflowStepExecutionRecord) -> bool:
    return step.status in _TERMINAL_STEP_STATUSES


def research_outcome(status: Any, error: Any) -> ResearchCallOutcome | None:
    """Outcome of one recorded research call. Skipped / refused calls never
    reached a backend and are not calls (None)."""
    status = str(getattr(status, "value", status) or "").lower()
    if status == "executed":
        return ResearchCallOutcome.OK
    if status == "failed":
        if str(error or "").lower().startswith("timeout"):
            return ResearchCallOutcome.TIMEOUT
        return ResearchCallOutcome.FAILED
    return None


def _research_calls(output: dict[str, Any]) -> list[tuple[str, ResearchCallOutcome]]:
    """(source, outcome) per research call recorded on a step output:
    research_delegations (ResearchResult dicts, any source) and
    vector_store_interactions (BoundedResearchTool's audit list)."""
    calls: list[tuple[str, ResearchCallOutcome]] = []
    for item in output.get("research_delegations") or []:
        if not isinstance(item, dict):
            continue
        outcome = research_outcome(item.get("status"), item.get("error"))
        if outcome is not None:
            source = item.get("source")
            calls.append((_dim(getattr(source, "value", source)), outcome))
    for item in output.get("vector_store_interactions") or []:
        if not isinstance(item, dict):
            continue
        outcome = research_outcome(item.get("status"), item.get("error"))
        if outcome is not None:
            calls.append(("vector_store", outcome))
    return calls


def _duration_measures(seconds: float | None) -> dict[str, float]:
    if seconds is None:
        return {}
    seconds = max(seconds, 0.0)
    return {
        DURATION_COUNT: 1,
        DURATION_SUM_SECONDS: seconds,
        _bucket(DURATION_BUCKETS, seconds): 1,
    }


def step_contributions(
    step: WorkflowStepExecutionRecord,
    alert_dimensions: tuple[tuple[str, str], ...],
    *,
    is_reexecution: bool,
    model: str | None,
) -> list[TechnicalContribution]:
    """Everything one finished step execution adds. `model` is the model
    the step was configured with (None = not an LLM step). A step that
    reported tokens always counts as an LLM call; a failed step counts as
    an errored LLM call only when it is an LLM step."""
    if not is_finished(step):
        return []
    succeeded = step.status == WorkflowStepStatus.SUCCEEDED
    output = step.output or {}
    duration = (
        (step.finished_at - step.started_at).total_seconds()
        if step.started_at is not None and step.finished_at is not None
        else None
    )
    step_dims = alert_dimensions + (("step_name", _dim(step.step_name)),)

    step_measures: dict[str, float] = {
        COUNT: 1,
        SUCCEEDED_COUNT if succeeded else FAILED_COUNT: 1,
        **_duration_measures(duration),
    }
    if is_reexecution:
        step_measures[RETRY_COUNT] = 1
    parts = [
        TechnicalContribution(MetricsDataType.WORKFLOW_STEP, step_dims, step_measures)
    ]

    input_tokens, output_tokens = sum_step_tokens([step])
    if input_tokens or output_tokens or (model is not None and not succeeded):
        llm_measures: dict[str, float] = {
            COUNT: 1,
            INPUT_TOKENS: input_tokens,
            OUTPUT_TOKENS: output_tokens,
            **_duration_measures(duration),
        }
        if not succeeded:
            llm_measures[ERROR_COUNT] = 1
        parts.append(
            TechnicalContribution(
                MetricsDataType.LLM_CALL,
                step_dims + (("model", _dim(model)),),
                llm_measures,
            )
        )

    research: dict[str, dict[str, float]] = {}
    for source, outcome in _research_calls(output):
        measures = research.setdefault(source, {})
        measures[COUNT] = measures.get(COUNT, 0) + 1
        name = RESEARCH_OUTCOME_MEASURES[outcome]
        measures[name] = measures.get(name, 0) + 1
    for source, measures in sorted(research.items()):
        parts.append(
            TechnicalContribution(
                MetricsDataType.RESEARCH_CALL,
                step_dims + (("source", source),),
                measures,
            )
        )
    return parts


def evaluation_contribution(
    alert_dimensions: tuple[tuple[str, str], ...],
    *,
    hallucination: bool | None,
    data_use_correct: bool | None,
) -> TechnicalContribution:
    """One judged alert. A verdict with either flag missing is invalid."""
    if hallucination is None or data_use_correct is None:
        measures: dict[str, float] = {INVALID_COUNT: 1}
    else:
        measures = {COUNT: 1}
        if hallucination:
            measures[HALLUCINATION_COUNT] = 1
        if data_use_correct:
            measures[DATA_USE_CORRECT_COUNT] = 1
    return TechnicalContribution(MetricsDataType.EVALUATION, alert_dimensions, measures)


_DIMENSION_ORDER = {
    MetricsDataType.WORKFLOW_STEP: WORKFLOW_STEP_DIMENSIONS,
    MetricsDataType.LLM_CALL: LLM_CALL_DIMENSIONS,
    MetricsDataType.RESEARCH_CALL: RESEARCH_CALL_DIMENSIONS,
    MetricsDataType.EVALUATION: EVALUATION_DIMENSIONS,
}


def technical_deltas(
    parts: list[TechnicalContribution],
    created_at: datetime,
    now: datetime,
    tz: tzinfo | str,
) -> list[RollupDelta]:
    """+contribution on every live level for the alert's local date/hour.
    Zero measures are dropped (a step that used no tokens adds no
    `input_tokens` attribute)."""
    zone = _zone(tz)
    local = created_at.astimezone(zone)
    today = now.astimezone(zone).date()
    deltas: list[RollupDelta] = []
    for part in parts:
        expected = _DIMENSION_ORDER.get(part.data_type)
        if (
            expected is not None
            and tuple(name for name, _ in part.dimensions) != expected
        ):
            raise ValueError(f"{part.data_type.value} dimensions must be {expected}")
        measures = {name: value for name, value in part.measures.items() if value != 0}
        if not measures:
            continue
        for level, period in live_periods(local.date(), today):
            deltas.append(
                RollupDelta(
                    key=RollupKey(
                        data_type=part.data_type,
                        level=level,
                        period=period,
                        dimensions=part.dimensions,
                    ),
                    hour=local.hour,
                    measures=dict(measures),
                )
            )
    return deltas
