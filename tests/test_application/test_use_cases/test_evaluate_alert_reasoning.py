"""D6 EvaluateAlertReasoning: judge prompt built from the run's evidence +
reasoning steps, verdict stored once, counted once in the `evaluation`
rollups, no raw content in its span; deterministic sampling."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from src.application.dtos.reasoning_evaluation_dtos import EvaluateAlertReasoningInput
from src.application.ports.alert_reasoning_evaluation_port import (
    AlertReasoningEvaluationRecord,
    ReasoningEvaluationStatus,
)
from src.application.ports.llm_unit_of_work_factory_port import LLMUnitOfWorkFactory
from src.application.ports.llm_unit_of_work_port import (
    LLMInvocationResult,
    LLMMessage,
    LLMUnitOfWork,
)
from src.application.ports.metrics_rollup_port import MetricsDataType, RollupLevel
from src.application.ports.monitoring_port import MonitoringPort
from src.application.ports.monitoring_span_port import MonitoringSpan
from src.application.use_cases.metrics.evaluate_alert_reasoning import (
    PROMPT_VERSION,
    EvaluateAlertReasoning,
    is_sampled_for_evaluation,
)
from src.domain.alerts.entities import (
    AlertMetricsSnapshot,
    AlertRecord,
    AlertStatus,
)
from src.domain.workflows.entities import (
    WorkflowExecutionRecord,
    WorkflowStatus,
    WorkflowStepExecutionRecord,
    WorkflowStepStatus,
)

TZ = "America/Bogota"
NOW = datetime(2026, 10, 1, 15, 30, tzinfo=UTC)
CREATED = datetime(2026, 10, 1, 13, 0, tzinfo=UTC)
VERDICT = '{"hallucination": true, "data_use_correct": false, "rationale": "Cita un monto que no está en el payload."}'


# --- fakes ---------------------------------------------------------------------


class ScriptedLLMUnitOfWork(LLMUnitOfWork):
    def __init__(self, factory: ScriptedLLMFactory) -> None:
        self._factory = factory

    def invoke(self, messages: list[LLMMessage]) -> LLMInvocationResult:
        self._factory.prompts.append(messages)
        queued = self._factory.queued
        answer = queued.pop(0) if queued else self._factory.answer
        return LLMInvocationResult(
            content=answer,
            model="judge-model",
            input_tokens=900,
            output_tokens=40,
        )


class ScriptedLLMFactory(LLMUnitOfWorkFactory):
    def __init__(self, answer: str = VERDICT) -> None:
        self.answer = answer
        # Answers consumed first, one per call; then `answer` repeats.
        self.queued: list[str] = []
        self.prompts: list[list[LLMMessage]] = []
        self.models: list[str] = []

    def create(
        self, *, model, monitoring, operation_name, temperature=0.0, max_tokens=None
    ):
        self.models.append(model)
        return ScriptedLLMUnitOfWork(self)


class RecordingSpan(MonitoringSpan):
    def __init__(self) -> None:
        self.data: list[dict[str, Any]] = []

    def write_input(self, data):
        self.data.append(data)

    def write_result(self, data):
        self.data.append(data)

    def write_inner_logs(self, entries):
        self.data.append({"logs": entries})

    def write_operation_metas(self, metadata):
        self.data.append(metadata)

    def record_dependency(self, name, kind, metadata=None):
        pass

    def finish(self, error=None):
        pass


class RecordingMonitoring(MonitoringPort):
    def __init__(self) -> None:
        self.spans: list[tuple[str, dict, RecordingSpan]] = []

    def start(self, operation_name, operation_type, metadata=None):
        span = RecordingSpan()
        self.spans.append((operation_name, metadata or {}, span))
        return span


class Alerts:
    def __init__(self, *alerts) -> None:
        self.alerts = {a.id: a for a in alerts}

    def get(self, alert_id):
        return self.alerts.get(alert_id)


class Workflows:
    def __init__(self, *workflows) -> None:
        self.workflows = {w.id: w for w in workflows}

    def get(self, workflow_id):
        return self.workflows.get(workflow_id)


class Steps:
    def __init__(self, steps) -> None:
        self.steps = list(steps)

    def list_by_workflow(self, workflow_execution_id):
        return [
            s for s in self.steps if s.workflow_execution_id == workflow_execution_id
        ]


class InMemoryEvaluations:
    def __init__(self) -> None:
        self.records: dict[UUID, AlertReasoningEvaluationRecord] = {}

    def create(self, record):
        return self.records.setdefault(record.alert_id, record)

    def get(self, alert_id):
        return self.records.get(alert_id)


class InMemoryRollups:
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

    def total(self, measure, level=RollupLevel.DAY) -> float:
        return sum(
            sum(m.get(measure, [0.0] * 24))
            for key, m in self.rows.items()
            if key.data_type == MetricsDataType.EVALUATION and key.level == level
        )


# --- setup -----------------------------------------------------------------------


def _step(workflow_id, name, output, *, offset=0, status=WorkflowStepStatus.SUCCEEDED):
    at = CREATED + timedelta(seconds=offset)
    return WorkflowStepExecutionRecord(
        id=uuid4(),
        workflow_execution_id=workflow_id,
        step_name=name,
        status=status,
        attempt=1,
        input={},
        output=output,
        error=None,
        started_at=at,
        finished_at=at,
        created_at=at,
        updated_at=at,
    )


def _world(steps_for=None, answer=VERDICT):
    alert = AlertRecord(
        id=uuid4(),
        event_id="e",
        event_type="t",
        input={"amount": {"baseValue": 1500}},
        status=AlertStatus.CLOSED,
        created_at=CREATED,
        updated_at=CREATED,
        metrics=AlertMetricsSnapshot(channel="WEB", status=AlertStatus.CLOSED),
    )
    workflow = WorkflowExecutionRecord(
        id=uuid4(),
        alert_id=alert.id,
        async_operation_id=uuid4(),
        workflow_name="alert_review",
        status=WorkflowStatus.SUCCEEDED,
        input={"alert_payload": {"amount": {"baseValue": 1500}}},
        output=None,
        error=None,
        current_step=None,
        feedback_iterations=0,
        max_feedback_iterations=2,
        created_at=CREATED,
        updated_at=CREATED,
    )
    steps = (steps_for or _default_steps)(workflow.id)
    llm, monitoring = ScriptedLLMFactory(answer), RecordingMonitoring()
    evaluations, rollups = InMemoryEvaluations(), InMemoryRollups()
    use_case = EvaluateAlertReasoning(
        llm_unit_of_work_factory=llm,
        monitoring=monitoring,
        model="judge-cfg",
        alert_repository=Alerts(alert),
        workflow_repository=Workflows(workflow),
        step_repository=Steps(steps),
        evaluation_repository=evaluations,
        rollup_repository=rollups,
        timezone_name=TZ,
        clock=lambda: NOW,
    )
    return dict(
        alert=alert,
        workflow=workflow,
        use_case=use_case,
        llm=llm,
        monitoring=monitoring,
        evaluations=evaluations,
        rollups=rollups,
    )


def _default_steps(workflow_id):
    return [
        _step(workflow_id, "pre_process", {"mandatory_fields": {"amount": 1500}}),
        _step(
            workflow_id,
            "classification",
            {"is_fraud": "not_fraud", "reasoning": "first"},
            offset=1,
        ),
        _step(
            workflow_id,
            "classification",
            {
                "is_fraud": "fraud",
                "fraud_classification": "ato",
                "reasoning": "monto 9999 inusual",
                "cot": "Observation: historial vacío",
                "input_tokens": 10,
            },
            offset=2,
        ),
        _step(
            workflow_id,
            "analyst",
            {"decision": "block", "reasoning": "bloquear"},
            offset=3,
        ),
        _step(workflow_id, "executor", {"executed_action": "block"}, offset=4),
    ]


def _run(world):
    return world["use_case"].execute(
        EvaluateAlertReasoningInput(world["alert"].id, world["workflow"].id)
    )


# --- tests ------------------------------------------------------------------------


def test_judges_latest_reasoning_against_evidence_and_counts_it() -> None:
    world = _world()
    out = _run(world)

    record = out.evaluation
    assert out.counted is True
    assert record.status == ReasoningEvaluationStatus.EVALUATED
    assert (record.hallucination, record.data_use_correct) == (True, False)
    assert record.judge_model == "judge-model"
    assert (record.input_tokens, record.output_tokens) == (900, 40)
    assert world["llm"].models == ["judge-cfg"]

    user_prompt = world["llm"].prompts[0][1].content
    assert "monto 9999 inusual" in user_prompt  # latest classification
    assert '"reasoning": "first"' not in user_prompt  # superseded attempt
    assert "Observation: historial vacío" in user_prompt  # the step's own evidence
    assert "1500" in user_prompt  # payload evidence
    assert "[analyst]" in user_prompt and "[executor]" not in user_prompt

    rollups = world["rollups"]
    for level in RollupLevel:
        assert rollups.total("count", level) == 1
        assert rollups.total("hallucination_count", level) == 1
        assert rollups.total("data_use_correct_count", level) == 0


def test_span_carries_no_prompt_or_rationale() -> None:
    world = _world()
    _run(world)
    name, metadata, span = world["monitoring"].spans[0]
    assert name == "evaluate_alert_reasoning"
    dumped = json.dumps([metadata, span.data], default=str)
    assert "monto 9999" not in dumped
    assert "Cita un monto" not in dumped
    assert '"hallucination": true' in dumped


def test_rerun_reuses_verdict_and_counts_once() -> None:
    world = _world()
    _run(world)
    again = _run(world)

    assert again.counted is False
    assert len(world["llm"].prompts) == 1  # never re-judged
    assert world["rollups"].total("count") == 1


def test_stored_but_uncounted_verdict_is_counted_on_retry() -> None:
    """Crash between storing the verdict and counting it."""
    world = _world()
    record = AlertReasoningEvaluationRecord(
        alert_id=world["alert"].id,
        workflow_execution_id=world["workflow"].id,
        status=ReasoningEvaluationStatus.EVALUATED,
        hallucination=False,
        data_use_correct=True,
        rationale="ok",
        judge_model="m",
        evaluated_at=NOW,
    )
    world["evaluations"].records[record.alert_id] = record

    out = _run(world)
    assert out.counted is True
    assert world["llm"].prompts == []
    assert world["rollups"].total("data_use_correct_count") == 1


def test_unparseable_answer_is_stored_invalid_and_kept_out_of_rates() -> None:
    world = _world(answer="no sé")
    out = _run(world)
    assert out.evaluation.status == ReasoningEvaluationStatus.INVALID
    assert world["rollups"].total("count") == 0
    assert world["rollups"].total("invalid_count") == 1


def test_answer_wrapped_in_prose_is_parsed() -> None:
    world = _world(answer="Aquí va:\n" + VERDICT + "\nFin.")
    assert _run(world).evaluation.status == ReasoningEvaluationStatus.EVALUATED


def test_nothing_to_judge_without_reasoning_steps() -> None:
    world = _world(
        steps_for=lambda wid: [
            _step(wid, "pre_process", {}),
            _step(wid, "deterministic", {"matched": True}),
        ]
    )
    out = _run(world)
    assert out.evaluation is None and out.counted is False
    assert world["llm"].prompts == [] and world["evaluations"].records == {}


def test_sampling_is_deterministic_and_bounded() -> None:
    ids = [uuid4() for _ in range(4000)]
    assert not any(is_sampled_for_evaluation(i, 0) for i in ids)
    assert all(is_sampled_for_evaluation(i, 1) for i in ids)
    sampled = [i for i in ids if is_sampled_for_evaluation(i, 0.05)]
    assert 100 < len(sampled) < 320
    assert sampled == [i for i in ids if is_sampled_for_evaluation(i, 0.05)]
    # A higher rate keeps every alert a lower rate sampled.
    assert all(is_sampled_for_evaluation(i, 0.2) for i in sampled)


@pytest.mark.parametrize("rate", [-1, 0.0])
def test_zero_or_negative_rate_disables(rate) -> None:
    assert is_sampled_for_evaluation(uuid4(), rate) is False


def _judged_steps(world) -> list[str]:
    prompt = world["llm"].prompts[0][1].content
    return re.findall(r"^\[(\w+)\]", prompt, re.MULTILINE)


def test_per_step_verdicts_derive_the_alert_verdict_and_record_the_prompt_version() -> (
    None
):
    steps = _judged_steps(_with_probe())
    assert len(steps) >= 2

    fresh = _world()
    fresh["llm"].queued.append(
        json.dumps(
            {
                "steps": {
                    name: {
                        "hallucination": name == steps[0],
                        "data_use_correct": name != steps[1],
                        "note": f"nota {name}",
                    }
                    for name in steps
                },
                "rationale": "resumen",
            }
        )
    )
    record = _run(fresh).evaluation

    # ANY step hallucinating flags the alert; ALL steps must use data correctly.
    assert (record.hallucination, record.data_use_correct) == (True, False)
    assert record.prompt_version == PROMPT_VERSION and record.attempts == 1
    assert set(record.step_verdicts) == set(steps)
    assert record.step_verdicts[steps[0]] == {
        "hallucination": True,
        "data_use_correct": True,
        "note": f"nota {steps[0]}",
    }
    assert record.step_verdicts[steps[1]]["data_use_correct"] is False
    assert "nombre del paso" in fresh["llm"].prompts[0][0].content


def test_a_clean_per_step_answer_is_not_a_hallucination() -> None:
    steps = _judged_steps(_with_probe())
    world = _world()
    world["llm"].queued.append(
        json.dumps(
            {
                "steps": {
                    n: {"hallucination": False, "data_use_correct": True, "note": ""}
                    for n in steps
                },
                "rationale": "",
            }
        )
    )

    record = _run(world).evaluation

    assert (record.hallucination, record.data_use_correct) == (False, True)


def _with_probe():
    """A world whose first judge call already happened, to read the step names."""
    world = _world()
    _run(world)
    return world


def test_a_v1_shaped_answer_is_still_accepted_without_step_detail() -> None:
    record = _run(_world()).evaluation  # the default VERDICT has no "steps"

    assert record.status == ReasoningEvaluationStatus.EVALUATED
    assert record.step_verdicts == {}


def test_an_answer_that_skips_a_step_is_not_trusted_as_per_step() -> None:
    steps = _judged_steps(_with_probe())
    partial = _world()
    partial["llm"].queued.append(
        json.dumps(
            {
                "steps": {
                    steps[0]: {
                        "hallucination": True,
                        "data_use_correct": True,
                        "note": "",
                    }
                }
            }
        )
    )

    record = _run(partial).evaluation

    # Not a complete per-step verdict and no top-level flags: unparseable, retried.
    assert partial["llm"].prompts and len(partial["llm"].prompts) == 2
    assert record.step_verdicts == {}


def test_an_unparseable_first_answer_is_retried_once_and_tokens_add_up() -> None:
    world = _world()
    world["llm"].queued.append("no sé")

    out = _run(world)

    assert len(world["llm"].prompts) == 2
    assert out.evaluation.status == ReasoningEvaluationStatus.EVALUATED
    assert out.evaluation.attempts == 2
    assert (out.evaluation.input_tokens, out.evaluation.output_tokens) == (1800, 80)
    assert world["rollups"].total("count") == 1


def test_two_unparseable_answers_stop_after_two_calls_and_stay_invalid() -> None:
    world = _world(answer="no sé")

    out = _run(world)

    assert len(world["llm"].prompts) == 2
    assert out.evaluation.status == ReasoningEvaluationStatus.INVALID
    assert out.evaluation.attempts == 2
    assert world["rollups"].total("invalid_count") == 1


def test_a_judge_that_is_also_a_reasoning_model_is_reported() -> None:
    from src.application.use_cases.metrics.evaluate_alert_reasoning import (
        judge_overlaps_reasoning,
    )

    models = {
        "detector": "gpt-a",
        "classification": "gpt-a",
        "analyst": "gpt-b",
        "adversarial": "",
    }

    assert judge_overlaps_reasoning("gpt-a", models) == ("classification", "detector")
    assert judge_overlaps_reasoning("gpt-c", models) == ()
    # No judge configured yet (falls back to the report model elsewhere): nothing to compare.
    assert judge_overlaps_reasoning("", models) == ()
