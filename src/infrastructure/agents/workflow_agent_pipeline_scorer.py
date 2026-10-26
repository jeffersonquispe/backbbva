from __future__ import annotations

import json
import time
from typing import Any
from uuid import uuid4

from src.application.dtos.test_run_dtos import StartTestRunInput
from src.application.ports.agent_experiment_component_port import ResolvedAgentComponent
from src.application.ports.agent_pipeline_scorer_port import AgentPipelineScore
from src.application.ports.alert_schema_port import (
    AlertSchemaDataSource,
    AlertSchemaRepository,
)
from src.application.ports.workflow_port import WorkflowExecutionRepository
from src.application.ports.workflow_step_execution_port import (
    WorkflowStepExecutionRepository,
)
from src.application.use_cases.test_runs.delete_test_runs import (
    DeleteTestRunsUseCase,
)
from src.application.use_cases.test_runs.start_test_run import StartTestRunUseCase
from src.domain.alerts.entities import AlertOrigin
from src.domain.alerts.exceptions import AdversarialFeedbackLimitExceededError
from src.domain.configurations.entities import ConfigurationRef
from src.domain.datasets.mature_sample_entities import (
    OPTIMIZER_REPLAY_HISTORY_COLUMN,
    DatasetSnapshot,
)
from src.domain.test_runs.entities import TestRunConfig
from src.domain.workflows.entities import WorkflowStatus

_REQUIRED_COMPONENTS = frozenset({"model", "configuration", "library", "vector_store"})
_TERMINAL_STATUSES = frozenset({WorkflowStatus.SUCCEEDED, WorkflowStatus.FAILED})
_FRAUD_DECISIONS = frozenset({"fraud", "risk", "fraudulent"})
_NO_FRAUD_DECISIONS = frozenset({"not_fraud", "no_fraud", "no-risk", "pass"})


class WorkflowAgentPipelineScorer:
    """Run each pinned stack through the production alert workflow.

    Replays use the existing test-run lifecycle with an optimizer-only origin.
    This keeps labels out of the score input, disables operational side effects
    and removes the temporary alert/workflow records after collecting results.
    """

    def __init__(
        self,
        *,
        start_test_run: StartTestRunUseCase,
        schemas: AlertSchemaRepository,
        workflows: WorkflowExecutionRepository,
        steps: WorkflowStepExecutionRepository,
        delete_test_runs: DeleteTestRunsUseCase,
        preserve_test_data: bool = False,
        timeout_seconds: int = 1800,
        poll_interval_seconds: float = 0.25,
    ) -> None:
        self._start_test_run = start_test_run
        self._schemas = schemas
        self._workflows = workflows
        self._steps = steps
        self._delete_test_runs = delete_test_runs
        self._preserve_test_data = preserve_test_data
        self._timeout_seconds = timeout_seconds
        self._poll_interval_seconds = poll_interval_seconds

    def predict_positive(
        self,
        components: tuple[ResolvedAgentComponent, ...],
        rows: list[dict[str, Any]],
        *,
        snapshot: DatasetSnapshot,
    ) -> AgentPipelineScore:
        by_type = {item.reference.component: item for item in components}
        if set(by_type) != _REQUIRED_COMPONENTS:
            raise ValueError("COMPLETE_COMPONENT_STACK_REQUIRED")
        if not rows:
            raise ValueError("PIPELINE_REPLAY_ROWS_REQUIRED")
        if not snapshot.schema_versions:
            raise ValueError("PIPELINE_REPLAY_SCHEMA_REQUIRED")
        schema_version = snapshot.schema_versions[0]
        schema = self._schemas.get(schema_version)
        if schema is None:
            raise ValueError("PIPELINE_REPLAY_SCHEMA_PIN_UNRESOLVED")

        configuration = by_type["configuration"]
        model = by_type["model"].content
        if not isinstance(configuration.content, dict) or not isinstance(model, dict):
            raise ValueError("PIPELINE_REPLAY_COMPONENT_INVALID")
        try:
            version = int(configuration.reference.version)
        except (TypeError, ValueError) as error:
            raise ValueError("PIPELINE_REPLAY_CONFIGURATION_PIN_INVALID") from error
        model_id = model.get("model_id")
        artifact_sha256 = model.get("artifact_sha256")
        if not isinstance(model_id, str) or not isinstance(artifact_sha256, str):
            raise ValueError("PIPELINE_REPLAY_MODEL_PIN_INVALID")
        library = by_type["library"]
        vector_store = by_type["vector_store"]
        vector_content = vector_store.content
        instance = (
            vector_content.get("instance") if isinstance(vector_content, dict) else None
        )
        if (
            not isinstance(instance, dict)
            or instance.get("id") != vector_store.reference.entity_id
        ):
            raise ValueError("PIPELINE_REPLAY_VECTOR_STORE_PIN_INVALID")
        if instance.get("version") != int(vector_store.reference.version):
            raise ValueError("PIPELINE_REPLAY_VECTOR_STORE_VERSION_INVALID")

        config_ref = ConfigurationRef(
            configuration_id=configuration.reference.entity_id,
            version=version,
        )
        run_input = StartTestRunInput(
            name=f"optimizer-replay-{uuid4()}",
            dataset_name=f"snapshot:{snapshot.snapshot_id}:final",
            config=TestRunConfig(
                max_feedback_iterations=1,
                configuration_ref=config_ref,
                schema_version=schema_version,
            ),
            rows_override=[
                _snapshot_row_to_alert_payload(row, schema, index)
                for index, row in enumerate(rows)
            ],
            origin=AlertOrigin.OPTIMIZER_EVALUATION,
            optimizer_model_pin={
                "model_id": model_id,
                "artifact_sha256": artifact_sha256,
            },
            optimizer_component_pins={
                "library": {
                    "entity_id": library.reference.entity_id,
                    "version": library.reference.version,
                    "content_sha256": library.reference.content_sha256,
                },
                "vector_store": {
                    "entity_id": vector_store.reference.entity_id,
                    "version": vector_store.reference.version,
                    "content_sha256": vector_store.reference.content_sha256,
                },
            },
        )
        started = self._start_test_run.execute(run_input)
        terminal = False
        try:
            workflows = self._wait_for_workflows(started.test_run_id, len(rows))
            terminal = True
            indexed = self._index_workflows(workflows, len(rows))
            predictions: list[bool] = []
            undecided = 0
            for workflow in indexed:
                if workflow.status != WorkflowStatus.SUCCEEDED:
                    # Production escalates these alerts to an analyst, so the
                    # stack reached no decision: count it as undecided rather
                    # than failing the whole candidate on one alert.
                    if AdversarialFeedbackLimitExceededError.matches(workflow.error):
                        predictions.append(False)
                        undecided += 1
                        continue
                    raise ValueError("PIPELINE_REPLAY_WORKFLOW_FAILED")
                decision = self._workflow_decision(workflow.id)
                if decision in _FRAUD_DECISIONS:
                    predictions.append(True)
                elif decision in _NO_FRAUD_DECISIONS:
                    predictions.append(False)
                else:
                    # An inconclusive outcome is counted against positive
                    # recall, matching the existing mature-evaluation policy;
                    # it is also reported separately as decision coverage.
                    predictions.append(False)
                    undecided += 1
            evidence_count = self._knowledge_evidence_count(by_type["vector_store"])
            return AgentPipelineScore(
                predictions=predictions,
                knowledge_evidence_asset_count=evidence_count,
                undecided_count=undecided,
            )
        finally:
            # Do not delete a still-running workflow on timeout. Its worker
            # must finish against durable state; retention cleanup can remove
            # it once terminal. Completed runs are removed immediately so
            # replay payloads do not linger in test-run or alert history.
            if terminal and not self._preserve_test_data:
                self._delete_test_runs.execute_for_ids([started.test_run_id])

    def _wait_for_workflows(self, test_run_id, expected_count: int):
        deadline = time.monotonic() + self._timeout_seconds
        while time.monotonic() < deadline:
            workflows = self._workflows.list_by_test_run(test_run_id)
            if len(workflows) > expected_count:
                raise ValueError("PIPELINE_REPLAY_WORKFLOW_COUNT_INVALID")
            if len(workflows) == expected_count and all(
                workflow.status in _TERMINAL_STATUSES for workflow in workflows
            ):
                return workflows
            time.sleep(self._poll_interval_seconds)
        raise TimeoutError("PIPELINE_REPLAY_TIMEOUT")

    @staticmethod
    def _index_workflows(workflows, expected_count: int):
        indexed: list[tuple[int, Any]] = []
        for workflow in workflows:
            row_index = (workflow.input or {}).get("optimizer_row_index")
            if isinstance(row_index, bool) or not isinstance(row_index, int):
                raise ValueError("PIPELINE_REPLAY_ROW_INDEX_MISSING")
            indexed.append((row_index, workflow))
        indexed.sort(key=lambda item: item[0])
        if [index for index, _ in indexed] != list(range(expected_count)):
            raise ValueError("PIPELINE_REPLAY_ROW_INDEX_INVALID")
        return [workflow for _, workflow in indexed]

    def _workflow_decision(self, workflow_id) -> str:
        records = self._steps.list_by_workflow(workflow_id)
        for step_name in ("classification", "detector", "deterministic"):
            attempts = [
                step
                for step in records
                if step.step_name == step_name and step.output is not None
            ]
            if not attempts:
                continue
            output = max(attempts, key=lambda step: step.attempt).output or {}
            if step_name == "deterministic":
                if not output.get("matched"):
                    continue
                decision = str(output.get("decision") or "").strip().lower()
                if decision in {"risk_suspected", "risk-suspected"}:
                    return "unknown"
                return decision
            return str(output.get("is_fraud") or "").strip().lower()
        return "unknown"

    @staticmethod
    def _knowledge_evidence_count(component: ResolvedAgentComponent) -> int:
        content = component.content
        assets = content.get("assets", []) if isinstance(content, dict) else []
        return len(assets) if isinstance(assets, list) else 0


def _snapshot_row_to_alert_payload(row, schema, row_index: int) -> dict[str, Any]:
    """Rebuild the schema's external payload shape from canonical snapshot fields."""
    payload: dict[str, Any] = {}
    for field in schema.fields:
        if (
            not field.is_alert
            or field.is_label
            or field.is_history
            or field.data_source == AlertSchemaDataSource.ARIA
            or field.field not in row
            or not field.field_ds_loc
        ):
            continue
        _set_payload_path(payload, field.field_ds_loc, row[field.field])

    customer_field_id = schema.field_roles.get("customer_id")
    if customer_field_id is not None:
        customer_field = next(
            (field for field in schema.fields if field.id == customer_field_id), None
        )
        if customer_field is not None and customer_field.field_ds_loc:
            _set_payload_path(
                payload,
                customer_field.field_ds_loc,
                f"{900_000_000_000 + row_index:012d}",
            )
    raw_history = row.get(OPTIMIZER_REPLAY_HISTORY_COLUMN)
    if raw_history:
        if isinstance(raw_history, str):
            try:
                raw_history = json.loads(raw_history)
            except json.JSONDecodeError as error:
                raise ValueError("PIPELINE_REPLAY_HISTORY_INVALID") from error
        if not isinstance(raw_history, list):
            raise ValueError("PIPELINE_REPLAY_HISTORY_INVALID")
        history_items: list[dict[str, Any]] = []
        for item in raw_history:
            if not isinstance(item, dict):
                raise ValueError("PIPELINE_REPLAY_HISTORY_INVALID")
            mapped: dict[str, Any] = {}
            for field in schema.fields:
                if (
                    not field.is_history
                    or field.is_label
                    or field.is_sensible
                    or field.field not in item
                    or not field.field_ds_loc
                ):
                    continue
                _set_payload_path(mapped, field.field_ds_loc, item[field.field])
            history_items.append(mapped)
        payload[OPTIMIZER_REPLAY_HISTORY_COLUMN] = history_items
    return payload


def _set_payload_path(payload: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    current = payload
    for part in parts[:-1]:
        next_value = current.setdefault(part, {})
        if not isinstance(next_value, dict):
            raise ValueError("PIPELINE_REPLAY_SCHEMA_PATH_CONFLICT")
        current = next_value
    current[parts[-1]] = value
