"""A2 GetTechnicalMetrics: totals, groups, 0-23 h profile, periods and
warnings read back from rows written by the real writers
(RecordWorkflowStepMetrics / evaluation_contribution)."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from src.application.dtos.metrics_dtos import MetricsQueryInput
from src.application.dtos.technical_metrics_dtos import RecordWorkflowStepMetricsInput
from src.application.ports.metrics_rollup_port import RollupRow
from src.application.use_cases.metrics.get_technical_metrics import GetTechnicalMetrics
from src.application.use_cases.metrics.record_workflow_step_metrics import (
    RecordWorkflowStepMetrics,
)
from src.application.use_cases.metrics.technical_rollup_contribution import (
    evaluation_contribution,
    technical_alert_dimensions,
    technical_deltas,
)
from src.domain.alerts.entities import (
    AlertMetricsSnapshot,
    AlertRecord,
    AlertStatus,
)
from src.domain.workflows.entities import (
    WorkflowStepExecutionRecord,
    WorkflowStepStatus,
)

TZ = "America/Bogota"
NOW = datetime(2026, 10, 1, 15, 30, tzinfo=UTC)  # 10:30 Bogota


class InMemoryRollupRepository:
    def __init__(self) -> None:
        self.markers: set = set()
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


class Alerts:
    def __init__(self) -> None:
        self.alerts: dict = {}

    def get(self, alert_id):
        return self.alerts.get(alert_id)


class Steps:
    def __init__(self) -> None:
        self.steps: list = []

    def list_by_workflow(self, workflow_execution_id):
        return [
            s for s in self.steps if s.workflow_execution_id == workflow_execution_id
        ]


def _record_alert(rollups, alerts, steps, *, created_at, channel, tier_version=1):
    alert = AlertRecord(
        id=uuid4(),
        event_id="e",
        event_type="t",
        input={},
        status=AlertStatus.CLOSED,
        created_at=created_at,
        updated_at=created_at,
        metrics=AlertMetricsSnapshot(
            channel=channel, status=AlertStatus.CLOSED, schema_version=tier_version
        ),
    )
    alerts.alerts[alert.id] = alert
    workflow_id = uuid4()
    for offset, (name, out, status) in enumerate(
        [
            ("pre_process", {}, WorkflowStepStatus.SUCCEEDED),
            (
                "classification",
                {
                    "input_tokens": 100,
                    "output_tokens": 10,
                    "vector_store_interactions": [{"status": "executed"}],
                },
                WorkflowStepStatus.SUCCEEDED,
            ),
            ("analyst", None, WorkflowStepStatus.FAILED),
        ]
    ):
        started = created_at + timedelta(seconds=offset * 5)
        steps.steps.append(
            WorkflowStepExecutionRecord(
                id=uuid4(),
                workflow_execution_id=workflow_id,
                step_name=name,
                status=status,
                attempt=1,
                input={},
                output=out,
                error=None,
                started_at=started,
                finished_at=started + timedelta(seconds=4),
                created_at=started,
                updated_at=started,
            )
        )
    RecordWorkflowStepMetrics(alerts, steps, rollups, TZ, clock=lambda: NOW).execute(
        RecordWorkflowStepMetricsInput(
            alert.id,
            workflow_id,
            step_models={"classification": "gpt-a", "analyst": "gpt-b"},
        )
    )
    return alert


def _use_case(rollups) -> GetTechnicalMetrics:
    return GetTechnicalMetrics(rollups, TZ, clock=lambda: NOW)


@pytest.fixture
def seeded():
    rollups, alerts, steps = InMemoryRollupRepository(), Alerts(), Steps()
    # 08:00 Bogota today (WEB) and 20:00 Bogota yesterday (APP, tier set v2).
    a = _record_alert(
        rollups,
        alerts,
        steps,
        created_at=datetime(2026, 10, 1, 13, tzinfo=UTC),
        channel="WEB",
    )
    b = _record_alert(
        rollups,
        alerts,
        steps,
        created_at=datetime(2026, 10, 1, 1, tzinfo=UTC),
        channel="APP",
        tier_version=2,
    )
    # One judged alert: hallucinated, data used incorrectly.
    part = evaluation_contribution(
        technical_alert_dimensions(a.metrics),
        hallucination=True,
        data_use_correct=False,
    )
    for delta in technical_deltas([part], a.created_at, NOW, TZ):
        for name, value in delta.measures.items():
            rollups.rows[delta.key][name][delta.hour] += value
    return rollups, a, b


def test_totals_groups_and_profile(seeded) -> None:
    rollups, _, _ = seeded
    out = _use_case(rollups).execute(MetricsQueryInput())  # last 24 h

    assert out.workflow_steps.executions == 6
    assert out.workflow_steps.failed == 2
    assert out.workflow_steps.duration.count == 6
    assert out.workflow_steps.duration.sum_seconds == pytest.approx(24)
    assert [s.step_name for s in out.workflow_steps_by_step] == [
        "analyst",
        "classification",
        "pre_process",
    ]
    assert out.llm_calls.calls == 4 and out.llm_calls.errors == 2
    assert (out.llm_calls.input_tokens, out.llm_calls.output_tokens) == (200, 20)
    assert {g.model: g.calls for g in out.llm_calls_by_model} == {
        "gpt-a": 2,
        "gpt-b": 2,
    }
    assert out.research_calls.calls == 2 and out.research_calls.ok == 2
    assert out.research_calls_by_source[0].source == "vector_store"
    assert (
        out.evaluations.evaluated,
        out.evaluations.hallucinations,
        out.evaluations.data_use_correct,
    ) == (1, 1, 0)

    hours = {slot.hour: slot for slot in out.hourly_profile}
    assert len(out.hourly_profile) == 24
    assert hours[8].step_executions == 3 and hours[20].step_executions == 3
    assert hours[8].input_tokens == 100
    assert [p.period for p in out.periods] == ["2026-09-30", "2026-10-01"]
    assert out.periods[1].hallucinations == 1
    assert {w.code for w in out.warnings} == {"schema_changed"}
    assert out.range.schema_versions == ["1", "2"]


def test_filters(seeded) -> None:
    rollups, _, _ = seeded
    use_case = _use_case(rollups)

    web = use_case.execute(MetricsQueryInput(filters={"channel": ["WEB"]}))
    assert web.workflow_steps.executions == 3
    assert web.evaluations.evaluated == 1

    # model applies to llm_call only; step_name to everything but evaluation.
    by_model = use_case.execute(MetricsQueryInput(filters={"model": ["gpt-a"]}))
    assert by_model.llm_calls.calls == 2
    assert by_model.workflow_steps.executions == 6
    by_step = use_case.execute(
        MetricsQueryInput(filters={"step_name": ["classification"]})
    )
    assert by_step.workflow_steps.executions == 2
    assert by_step.llm_calls.calls == 2
    assert by_step.evaluations.evaluated == 1


def test_range_excludes_hours_outside(seeded) -> None:
    rollups, _, _ = seeded
    out = _use_case(rollups).execute(
        MetricsQueryInput(
            from_=datetime(2026, 10, 1, 12, tzinfo=UTC),  # 07:00 Bogota
            to=NOW,
        )
    )
    assert out.workflow_steps.executions == 3


def test_unknown_filter_is_rejected(seeded) -> None:
    rollups, _, _ = seeded
    with pytest.raises(ValueError):
        _use_case(rollups).execute(MetricsQueryInput(filters={"customer_id": ["x"]}))
