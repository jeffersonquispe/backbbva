"""R8: RecordWorkflowStepMetrics + the pure technical contributions -
rows per step/LLM/research call, tokens identical to token_usage.py, and
exactly-once per step execution (apply_once markers)."""
from __future__ import annotations

import dataclasses
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from src.application.dtos.technical_metrics_dtos import RecordWorkflowStepMetricsInput
from src.application.ports.alert_port import (
    AlertMetricsSnapshot,
    AlertRecord,
    AlertResolutionMethod,
    AlertStatus,
)
from src.application.ports.metrics_rollup_port import (
    LLM_CALL_DIMENSIONS,
    RESEARCH_CALL_DIMENSIONS,
    WORKFLOW_STEP_DIMENSIONS,
    MetricsDataType,
    RollupLevel,
    RollupRow,
)
from src.application.ports.workflow_port import (
    WorkflowStepExecutionRecord,
    WorkflowStepStatus,
)
from src.application.use_cases.metrics.record_workflow_step_metrics import (
    RecordWorkflowStepMetrics,
)
from src.application.use_cases.metrics.technical_rollup_contribution import (
    research_outcome,
    step_contributions,
    technical_alert_dimensions,
    technical_deltas,
)
from src.application.use_cases.test_runs.token_usage import sum_step_tokens

TZ = "America/Bogota"
NOW = datetime(2026, 10, 1, 15, 30, tzinfo=UTC)
CREATED = datetime(2026, 10, 1, 4, 30, tzinfo=UTC)  # 23:30 Bogota, Sep 30


class InMemoryAlertRepository:
    def __init__(self, *alerts: AlertRecord) -> None:
        self.alerts = {a.id: a for a in alerts}

    def get(self, alert_id: UUID) -> AlertRecord | None:
        return self.alerts.get(alert_id)


class InMemoryStepRepository:
    def __init__(self) -> None:
        self.steps: list[WorkflowStepExecutionRecord] = []

    def list_by_workflow(self, workflow_execution_id: UUID) -> list[WorkflowStepExecutionRecord]:
        return [s for s in self.steps if s.workflow_execution_id == workflow_execution_id]


class InMemoryRollupRepository:
    def __init__(self) -> None:
        self.markers: set[tuple[str, str]] = set()
        self.rows: dict = defaultdict(lambda: defaultdict(lambda: [0.0] * 24))

    def apply_once(self, deltas, marker) -> bool:
        if (marker.scope, marker.key) in self.markers:
            return False
        self.markers.add((marker.scope, marker.key))
        for delta in deltas:
            for name, value in delta.measures.items():
                self.rows[delta.key][name][delta.hour] += value
        return True

    def query(self, data_type, level, periods, filters=None):
        return [
            RollupRow(key=key, measures={m: list(s) for m, s in measures.items()})
            for key, measures in self.rows.items()
            if key.data_type == data_type
            and key.level == level
            and key.period in periods
            and all(key.dimension(n) in v for n, v in (filters or {}).items())
        ]

    def total(self, data_type, measure, level=RollupLevel.DAY, **dims) -> float:
        return sum(
            sum(measures.get(measure, [0.0] * 24))
            for key, measures in self.rows.items()
            if key.data_type == data_type
            and key.level == level
            and all(key.dimension(n) == v for n, v in dims.items())
        )


def _alert(metrics: AlertMetricsSnapshot | None = None) -> AlertRecord:
    return AlertRecord(
        id=uuid4(),
        event_id="evt",
        event_type="transaction",
        input={},
        status=AlertStatus.CLOSED,
        created_at=CREATED,
        updated_at=CREATED,
        metrics=metrics,
    )


SNAPSHOT = AlertMetricsSnapshot(
    origin="production",
    segment="retail",
    channel="WEB",
    subchannel="PSE",
    amount_tier="high",
    schema_version=1,
    status=AlertStatus.CLOSED,
    configuration_id="cfg-1",
    resolution_method=AlertResolutionMethod.ARIA,
)


def _step(
    workflow_id: UUID,
    name: str,
    *,
    seconds: float = 2.0,
    status: WorkflowStepStatus = WorkflowStepStatus.SUCCEEDED,
    output: dict | None = None,
    offset: int = 0,
    attempt: int = 1,
) -> WorkflowStepExecutionRecord:
    started = CREATED + timedelta(seconds=10 + offset)
    finished = started + timedelta(seconds=seconds) if status != WorkflowStepStatus.RUNNING else None
    return WorkflowStepExecutionRecord(
        id=uuid4(),
        workflow_execution_id=workflow_id,
        step_name=name,
        status=status,
        attempt=attempt,
        input={},
        output=output,
        error=None if status != WorkflowStepStatus.FAILED else "boom",
        started_at=started,
        finished_at=finished,
        created_at=started,
        updated_at=finished or started,
    )


def _use_case(alerts, steps, rollups) -> RecordWorkflowStepMetrics:
    return RecordWorkflowStepMetrics(
        alert_repository=alerts,
        step_repository=steps,
        rollup_repository=rollups,
        timezone_name=TZ,
        clock=lambda: NOW,
    )


MODELS = {"classification": "gpt-a", "adversarial": "gpt-b", "analyst": "gpt-a"}


def _seed_run(steps: InMemoryStepRepository, workflow_id: UUID) -> None:
    steps.steps += [
        _step(workflow_id, "pre_process", seconds=0.4, output={"mandatory_fields": {}}),
        _step(
            workflow_id,
            "classification",
            seconds=12,
            offset=1,
            output={
                "input_tokens": 1000,
                "output_tokens": 50,
                "research_delegations": [
                    {"source": "history_pandas", "status": "executed", "error": None},
                    {"source": "history_pandas", "status": "failed", "error": "timeout: no respondió"},
                    {"source": "history_pandas", "status": "skipped", "error": "disabled"},
                ],
                "vector_store_interactions": [
                    {"status": "executed", "error": None},
                    {"status": "failed", "error": "connection refused"},
                    {"status": "refused", "error": "interaction budget exhausted"},
                ],
            },
        ),
        _step(workflow_id, "adversarial", seconds=3, offset=2, output={"input_tokens": 400, "output_tokens": 20}),
        # Feedback loop: classification again (attempt 2).
        _step(workflow_id, "classification", seconds=8, offset=3, attempt=2, output={"input_tokens": 900, "output_tokens": 40}),
        _step(workflow_id, "analyst", seconds=70, offset=4, status=WorkflowStepStatus.FAILED),
        _step(workflow_id, "executor", offset=5, status=WorkflowStepStatus.RUNNING),
    ]


def test_rows_per_step_llm_and_research_call() -> None:
    alert = _alert(SNAPSHOT)
    steps, rollups, workflow_id = InMemoryStepRepository(), InMemoryRollupRepository(), uuid4()
    _seed_run(steps, workflow_id)

    out = _use_case(InMemoryAlertRepository(alert), steps, rollups).execute(
        RecordWorkflowStepMetricsInput(alert.id, workflow_id, step_models=MODELS)
    )

    assert (out.recorded, out.already_recorded, out.not_finished) == (5, 0, 1)
    ws = MetricsDataType.WORKFLOW_STEP
    assert rollups.total(ws, "count") == 5
    assert rollups.total(ws, "succeeded_count") == 4
    assert rollups.total(ws, "failed_count") == 1
    assert rollups.total(ws, "retry_count", step_name="classification") == 1
    assert rollups.total(ws, "duration_sum_seconds") == pytest.approx(0.4 + 12 + 3 + 8 + 70)
    assert rollups.total(ws, "dur_lt_1s") == 1
    assert rollups.total(ws, "dur_gt_60s") == 1

    llm = MetricsDataType.LLM_CALL
    assert rollups.total(llm, "count") == 4  # 2 classification, adversarial, failed analyst
    assert rollups.total(llm, "error_count", model="gpt-a", step_name="analyst") == 1
    assert rollups.total(llm, "input_tokens", model="gpt-a") == 1900
    assert rollups.total(llm, "input_tokens", model="gpt-b") == 400

    rc = MetricsDataType.RESEARCH_CALL
    assert rollups.total(rc, "count", source="history_pandas") == 2
    assert rollups.total(rc, "ok_count", source="history_pandas") == 1
    assert rollups.total(rc, "timeout_count", source="history_pandas") == 1
    assert rollups.total(rc, "count", source="vector_store") == 2
    assert rollups.total(rc, "failed_count", source="vector_store") == 1

    # Every key carries the alert's technical dimensions in the fixed order.
    for key in rollups.rows:
        names = tuple(n for n, _ in key.dimensions)
        assert names == {
            ws: WORKFLOW_STEP_DIMENSIONS,
            llm: LLM_CALL_DIMENSIONS,
            rc: RESEARCH_CALL_DIMENSIONS,
        }[key.data_type]
        assert key.dimension("segment") == "retail"
        assert key.dimension("status") == "CLOSED"
        assert key.dimension("mark") is None


def test_tokens_equal_token_usage_on_every_level() -> None:
    alert = _alert(SNAPSHOT)
    steps, rollups, workflow_id = InMemoryStepRepository(), InMemoryRollupRepository(), uuid4()
    _seed_run(steps, workflow_id)
    _use_case(InMemoryAlertRepository(alert), steps, rollups).execute(
        RecordWorkflowStepMetricsInput(alert.id, workflow_id, step_models=MODELS)
    )

    expected = sum_step_tokens(steps.list_by_workflow(workflow_id))
    for level in RollupLevel:
        assert (
            rollups.total(MetricsDataType.LLM_CALL, "input_tokens", level),
            rollups.total(MetricsDataType.LLM_CALL, "output_tokens", level),
        ) == expected


def test_buckets_by_alert_arrival_in_bogota() -> None:
    alert = _alert(SNAPSHOT)
    steps, rollups, workflow_id = InMemoryStepRepository(), InMemoryRollupRepository(), uuid4()
    _seed_run(steps, workflow_id)
    _use_case(InMemoryAlertRepository(alert), steps, rollups).execute(
        RecordWorkflowStepMetricsInput(alert.id, workflow_id)
    )
    periods = {(k.level, k.period) for k in rollups.rows}
    assert periods == {
        (RollupLevel.DAY, "2026-09-30"),
        (RollupLevel.MONTH, "2026-09"),
        (RollupLevel.YEAR, "2026"),
    }
    key = next(iter(rollups.rows))
    assert any(rollups.rows[key][m][23] for m in rollups.rows[key])


def test_recording_again_counts_nothing_twice() -> None:
    """A Celery retry: the second attempt lists the first attempt's steps
    again plus its own new ones - only the new ones are counted."""
    alert = _alert(SNAPSHOT)
    steps, rollups, workflow_id = InMemoryStepRepository(), InMemoryRollupRepository(), uuid4()
    _seed_run(steps, workflow_id)
    use_case = _use_case(InMemoryAlertRepository(alert), steps, rollups)
    use_case.execute(RecordWorkflowStepMetricsInput(alert.id, workflow_id, step_models=MODELS))
    tokens_before = rollups.total(MetricsDataType.LLM_CALL, "input_tokens")

    again = use_case.execute(RecordWorkflowStepMetricsInput(alert.id, workflow_id, step_models=MODELS))
    assert (again.recorded, again.already_recorded) == (0, 5)
    assert rollups.total(MetricsDataType.LLM_CALL, "input_tokens") == tokens_before

    # Retry attempt re-runs pre_process (a re-execution) and the crashed
    # executor record now has a finished twin.
    steps.steps.append(_step(workflow_id, "pre_process", seconds=0.5, offset=10))
    third = use_case.execute(RecordWorkflowStepMetricsInput(alert.id, workflow_id, step_models=MODELS))
    assert (third.recorded, third.already_recorded) == (1, 5)
    assert rollups.total(MetricsDataType.WORKFLOW_STEP, "retry_count", step_name="pre_process") == 1


def test_alert_without_snapshot_counts_under_unknown() -> None:
    alert = _alert(None)
    steps, rollups, workflow_id = InMemoryStepRepository(), InMemoryRollupRepository(), uuid4()
    steps.steps.append(_step(workflow_id, "pre_process"))
    _use_case(InMemoryAlertRepository(alert), steps, rollups).execute(
        RecordWorkflowStepMetricsInput(alert.id, workflow_id)
    )
    key = next(iter(rollups.rows))
    assert key.dimension("segment") == "unknown"
    assert key.dimension("status") == "CLOSED"


def test_missing_alert_records_nothing() -> None:
    rollups = InMemoryRollupRepository()
    out = _use_case(InMemoryAlertRepository(), InMemoryStepRepository(), rollups).execute(
        RecordWorkflowStepMetricsInput(uuid4(), uuid4())
    )
    assert out.recorded == 0 and not rollups.rows


@pytest.mark.parametrize(
    "status, error, expected",
    [
        ("executed", None, "ok"),
        ("failed", "timeout: no respondió en 5 s", "timeout"),
        ("failed", "boom", "failed"),
        ("skipped", "disabled", None),
        ("refused", "budget", None),
    ],
)
def test_research_outcome(status, error, expected) -> None:
    outcome = research_outcome(status, error)
    assert (outcome.value if outcome else None) == expected


def test_deterministic_step_with_no_tokens_is_not_an_llm_call() -> None:
    step = _step(uuid4(), "profiling", output={"input_tokens": 0, "output_tokens": 0})
    parts = step_contributions(
        step, technical_alert_dimensions(SNAPSHOT), is_reexecution=False, model=None
    )
    assert [p.data_type for p in parts] == [MetricsDataType.WORKFLOW_STEP]


def test_day_rows_only_inside_retention() -> None:
    step = _step(uuid4(), "pre_process")
    parts = step_contributions(
        step, technical_alert_dimensions(SNAPSHOT), is_reexecution=False, model=None
    )
    old = CREATED - timedelta(days=120)
    levels = {d.key.level for d in technical_deltas(parts, old, NOW, TZ)}
    assert levels == {RollupLevel.MONTH, RollupLevel.YEAR}


def test_wrong_dimension_order_is_rejected() -> None:
    step = _step(uuid4(), "pre_process")
    part = step_contributions(
        step, technical_alert_dimensions(SNAPSHOT), is_reexecution=False, model=None
    )[0]
    broken = dataclasses.replace(part, dimensions=part.dimensions[1:])
    with pytest.raises(ValueError):
        technical_deltas([broken], CREATED, NOW, TZ)
