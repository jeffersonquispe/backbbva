from __future__ import annotations

import json
from datetime import UTC, date, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from src.application.dtos.test_run_dtos import StartTestRunOutput
from src.application.ports.agent_experiment_component_port import (
    ResolvedAgentComponent,
)
from src.domain.agents.experiment import ComponentVersionReference
from src.domain.agents.objective import AgentObjective, AgentObjectiveStatus
from src.domain.datasets.mature_sample_entities import (
    OPTIMIZER_REPLAY_HISTORY_COLUMN,
    DatasetSnapshot,
)
from src.domain.workflows.entities import (
    WorkflowExecutionRecord,
    WorkflowStatus,
    WorkflowStepExecutionRecord,
    WorkflowStepStatus,
)
from src.infrastructure.agents.workflow_agent_pipeline_scorer import (
    WorkflowAgentPipelineScorer,
)


class InMemoryWorkflowRepository:
    def __init__(self) -> None:
        self.items: dict[UUID, WorkflowExecutionRecord] = {}

    def list_by_test_run(self, test_run_id):
        return [item for item in self.items.values() if item.test_run_id == test_run_id]


class InMemoryStepRepository:
    def __init__(self) -> None:
        self.items: dict[UUID, list[WorkflowStepExecutionRecord]] = {}

    def list_by_workflow(self, workflow_id):
        return self.items.get(workflow_id, [])


class InMemorySchemaRepository:
    def get(self, version):
        return SimpleNamespace(
            version=version,
            field_roles={"customer_id": "customer-field"},
            fields=[
                SimpleNamespace(
                    id="amount-field",
                    data_source="aric",
                    field="amount",
                    field_ds_loc="amount_value",
                    is_alert=True,
                    is_label=False,
                    is_history=False,
                ),
                SimpleNamespace(
                    id="customer-field",
                    data_source="aric",
                    field="customer_id",
                    field_ds_loc="customerid",
                    is_alert=True,
                    is_label=False,
                    is_history=False,
                ),
                SimpleNamespace(
                    id="label-field",
                    data_source="aric",
                    field="fraud_label",
                    field_ds_loc="marcacion_final",
                    is_alert=True,
                    is_label=True,
                    is_history=False,
                ),
                SimpleNamespace(
                    id="history-geolocation",
                    data_source="host",
                    field="geolocation",
                    field_ds_loc="location.country",
                    is_alert=False,
                    is_label=False,
                    is_history=True,
                    is_sensible=False,
                ),
            ],
        )


class RecordingStartTestRun:
    def __init__(self, workflows, steps, decisions, errors=None):
        self.workflows = workflows
        self.steps = steps
        self.decisions = decisions
        # Row index -> error of a workflow that FAILED instead of deciding.
        self.errors = errors or {}
        self.input = None
        self.test_run_id = uuid4()

    def execute(self, input):
        self.input = input
        now = datetime.now(UTC)
        for index, decision in enumerate(self.decisions):
            workflow_id = uuid4()
            workflow = WorkflowExecutionRecord(
                id=workflow_id,
                alert_id=uuid4(),
                async_operation_id=uuid4(),
                workflow_name="alert_review",
                status=(
                    WorkflowStatus.FAILED
                    if index in self.errors
                    else WorkflowStatus.SUCCEEDED
                ),
                input={"optimizer_row_index": index},
                output=None,
                error=self.errors.get(index),
                current_step="post_process",
                feedback_iterations=0,
                max_feedback_iterations=1,
                created_at=now,
                updated_at=now,
                finished_at=now,
                test_run_id=self.test_run_id,
            )
            self.workflows.items[workflow_id] = workflow
            step = WorkflowStepExecutionRecord(
                id=uuid4(),
                workflow_execution_id=workflow_id,
                step_name="classification",
                status=WorkflowStepStatus.SUCCEEDED,
                attempt=1,
                input=None,
                output={"is_fraud": decision},
                error=None,
                started_at=now,
                finished_at=now,
                created_at=now,
                updated_at=now,
            )
            self.steps.items[workflow_id] = [step]
        return StartTestRunOutput(self.test_run_id, len(input.rows_override))


class RecordingDeleteTestRuns:
    def __init__(self):
        self.deleted = []

    def execute_for_ids(self, test_run_ids):
        self.deleted.extend(test_run_ids)


class InMemoryObjectiveRepository:
    def get(self, objective_id, version):
        return AgentObjective(
            objective_id=objective_id,
            version=version,
            success_label="fraud_label",
            positive_label="fraud",
            negative_label="no_fraud",
            maturing_days=30,
            expected_coverage_pct=95,
            stable_months=3,
            primary_metrics=("precision", "recall"),
            precision_floor=0,
            minimum_support_per_segment=30,
            minimum_global_support=1,
            minimum_count_to_publish_aggregates=1,
            minimum_mature_alert_coverage_pct=80,
            unlabeled_rule="exclude_pending_from_precision_and_recall",
            schema_mapping={},
            status=AgentObjectiveStatus.ACTIVE,
            created_by="test",
            created_at=datetime.now(UTC),
        )


def _snapshot() -> DatasetSnapshot:
    return DatasetSnapshot(
        snapshot_id="snapshot-final",
        specification={"as_of": "2026-10-22", "maturing_days": 30},
        period_start=date(2026, 4, 1),
        period_end=date(2026, 10, 1),
        maturing_days=30,
        strata_counts={},
        partition_counts={"final": 2},
        schema_versions=(4,),
        content_hash="a" * 64,
        trigger="test",
        dataset_refs={"final": "final-dataset"},
        created_at=datetime.now(UTC),
    )


def _components():
    contents = {
        "model": {"model_id": "model-1", "artifact_sha256": "b" * 64},
        "configuration": {"configuration_id": "cfg-1", "version": 2},
        "library": {"entry": "library"},
        "vector_store": {
            "instance": {"id": "vector_store-1", "version": 1},
            "generation": 1,
            "assets": [{"id": "asset-1"}],
        },
    }
    return tuple(
        ResolvedAgentComponent(
            reference=ComponentVersionReference.pin(
                component,
                "cfg-1" if component == "configuration" else f"{component}-1",
                "2" if component == "configuration" else "1",
                content,
            ),
            content=content,
        )
        for component, content in contents.items()
    )


def test_workflow_pipeline_scorer_replays_rows_and_cleans_completed_run():
    workflows = InMemoryWorkflowRepository()
    steps = InMemoryStepRepository()
    starter = RecordingStartTestRun(workflows, steps, ["fraud", "unknown"])
    cleanup = RecordingDeleteTestRuns()
    scorer = WorkflowAgentPipelineScorer(
        start_test_run=starter,
        schemas=InMemorySchemaRepository(),
        workflows=workflows,
        steps=steps,
        delete_test_runs=cleanup,
        timeout_seconds=1,
        poll_interval_seconds=0.001,
    )

    rows = [
        {
            "amount": 100,
            "fraud_label": "fraud",
            OPTIMIZER_REPLAY_HISTORY_COLUMN: json.dumps(
                [{"geolocation": "CO"}], separators=(",", ":")
            ),
        },
        {"amount": 200, "fraud_label": "pending"},
    ]
    result = scorer.predict_positive(_components(), rows, snapshot=_snapshot())

    assert result.predictions == [True, False]
    assert result.undecided_count == 1
    assert result.knowledge_evidence_asset_count == 1
    assert starter.input.rows_override == [
        {
            "amount_value": 100,
            "customerid": "900000000000",
            OPTIMIZER_REPLAY_HISTORY_COLUMN: [{"location": {"country": "CO"}}],
        },
        {"amount_value": 200, "customerid": "900000000001"},
    ]
    assert starter.input.config.configuration_ref.configuration_id == "cfg-1"
    assert starter.input.config.schema_version == 4
    assert cleanup.deleted == [starter.test_run_id]


def test_workflow_pipeline_scorer_preserves_completed_run_when_requested():
    workflows = InMemoryWorkflowRepository()
    steps = InMemoryStepRepository()
    starter = RecordingStartTestRun(workflows, steps, ["fraud", "unknown"])
    cleanup = RecordingDeleteTestRuns()
    scorer = WorkflowAgentPipelineScorer(
        start_test_run=starter,
        schemas=InMemorySchemaRepository(),
        workflows=workflows,
        steps=steps,
        delete_test_runs=cleanup,
        preserve_test_data=True,
        timeout_seconds=1,
        poll_interval_seconds=0.001,
    )

    scorer.predict_positive(
        _components(), [{"amount": 100}, {"amount": 200}], snapshot=_snapshot()
    )

    assert cleanup.deleted == []


def _scorer_with_errors(errors):
    workflows = InMemoryWorkflowRepository()
    steps = InMemoryStepRepository()
    starter = RecordingStartTestRun(
        workflows, steps, ["fraud", "fraud", "not_fraud"], errors=errors
    )
    cleanup = RecordingDeleteTestRuns()
    scorer = WorkflowAgentPipelineScorer(
        start_test_run=starter,
        schemas=InMemorySchemaRepository(),
        workflows=workflows,
        steps=steps,
        delete_test_runs=cleanup,
        timeout_seconds=1,
        poll_interval_seconds=0.001,
    )
    return scorer, cleanup


def test_workflow_pipeline_scorer_counts_escalated_alert_as_undecided():
    scorer, cleanup = _scorer_with_errors(
        {
            1: "Adversarial review (detector) still flagged issues after 1 "
            "feedback loop(s) back to detector: recount the history"
        }
    )

    result = scorer.predict_positive(
        _components(),
        [{"amount": 100}, {"amount": 200}, {"amount": 300}],
        snapshot=_snapshot(),
    )

    assert result.predictions == [True, False, False]
    assert result.undecided_count == 1
    assert len(cleanup.deleted) == 1


def test_workflow_pipeline_scorer_fails_candidate_on_other_workflow_errors():
    scorer, cleanup = _scorer_with_errors({1: "MCP scoring unavailable"})

    with pytest.raises(ValueError, match="PIPELINE_REPLAY_WORKFLOW_FAILED"):
        scorer.predict_positive(
            _components(),
            [{"amount": 100}, {"amount": 200}, {"amount": 300}],
            snapshot=_snapshot(),
        )
    assert len(cleanup.deleted) == 1


@pytest.mark.parametrize(
    "decision,expected",
    [("pass", "pass"), ("scale_to_analyst", "unknown"), ("handle_by_aria", "fraud")],
)
def test_pipeline_scorer_respects_first_adversarial_terminal_decision(
    decision, expected
):
    from dataclasses import replace

    workflows = InMemoryWorkflowRepository()
    steps = InMemoryStepRepository()
    starter = RecordingStartTestRun(workflows, steps, ["fraud"])
    scorer = WorkflowAgentPipelineScorer(
        start_test_run=starter,
        schemas=InMemorySchemaRepository(),
        workflows=workflows,
        steps=steps,
        delete_test_runs=RecordingDeleteTestRuns(),
        preserve_test_data=True,
        timeout_seconds=1,
        poll_interval_seconds=0.001,
    )
    scorer.predict_positive(_components(), [{"amount": 100}], snapshot=_snapshot())
    workflow_id, records = next(iter(steps.items.items()))
    review = replace(
        records[0],
        id=uuid4(),
        step_name="detector_adversarial",
        output={
            "decision": decision,
            "requires_classification_feedback": False,
        },
    )
    # An earlier internal correction must not hide the final routing decision.
    earlier = replace(
        review,
        id=uuid4(),
        attempt=0,
        output={
            "decision": "handle_by_aria",
            "requires_classification_feedback": True,
        },
    )
    steps.items[workflow_id] += [earlier, review]
    assert scorer._workflow_decision(workflow_id) == expected
