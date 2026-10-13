from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.application.dtos.run_alert_review_workflow_dtos import (
    RunAlertReviewWorkflowOutput,
)
from src.infrastructure.entrypoint.worker.celery import tasks


class RecordingUseCase:
    def __init__(self, output=None):
        self.output = output
        self.calls = []

    def execute(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        progress = kwargs.get("progress")
        if progress:
            progress({"stage": "working"})
        return self.output


class InMemoryOperationsRepository:
    def __init__(self):
        self.calls = []

    def update(self, *args, **kwargs):
        self.calls.append((args, kwargs))


def _factory(monkeypatch, module, name, fake):
    monkeypatch.setattr(module, name, lambda: fake)


def test_healthcheck_task():
    assert tasks.healthcheck.run() == {"status": "ok", "backend": "celery"}


def test_run_async_operation_task(monkeypatch):
    operation = SimpleNamespace(operation_type="unsupported")
    repository = InMemoryOperationsRepository()
    repository.get = lambda operation_id: operation
    monkeypatch.setattr(tasks, "get_async_operation_repository", lambda: repository)
    result = tasks.run_async_operation.run(str(uuid4()))
    assert result["status"] == "failed"
    assert repository.calls[0][1]["status"].value == "FAILED"


def test_reconcile_async_operations_task(monkeypatch):
    fake = RecordingUseCase(SimpleNamespace(inspected=0, updated=0, operations=[]))
    _factory(monkeypatch, tasks, "get_reconcile_async_operations_use_case", fake)
    assert tasks.reconcile_async_operations.run(12) == {
        "inspected": 0, "updated": 0, "operations": []
    }
    assert fake.calls[0][0][0].limit == 12


def test_cleanup_test_runs_task(monkeypatch):
    use_case = RecordingUseCase(SimpleNamespace(
        deleted_test_runs=1, deleted_cases=2, deferred_active_runs=3
    ))
    settings = SimpleNamespace(max_stored_test_runs=5, test_cleanup_policy="oldest")
    _factory(monkeypatch, tasks, "get_cleanup_test_runs_use_case", use_case)
    monkeypatch.setattr(tasks, "get_operational_settings_repository", lambda: SimpleNamespace(get=lambda: settings))
    assert tasks.cleanup_test_runs.run() == {
        "deleted_test_runs": 1, "deleted_cases": 2, "deferred_active_runs": 3
    }
    assert use_case.calls[0][0] == (5, "oldest")


def test_run_alert_review_workflow_task(monkeypatch):
    workflow_id = str(uuid4())
    fake = RecordingUseCase(RunAlertReviewWorkflowOutput("ok", workflow_id))
    _factory(monkeypatch, tasks, "get_run_alert_review_workflow_use_case", fake)
    assert tasks.run_alert_review_workflow.run(workflow_id) == {
        "status": "ok", "workflow_execution_id": workflow_id
    }
    assert fake.calls[0][1] == {"is_final_attempt": False}


def test_escalate_alert_task(monkeypatch):
    fake = RecordingUseCase()
    _factory(monkeypatch, tasks, "get_escalate_alert_to_analyst_use_case", fake)
    alert_id = str(uuid4())
    assert tasks.escalate_alert_to_analyst.run(alert_id, "evt", None, "reason")["alert_id"] == alert_id
    assert str(fake.calls[0][0][0].alert_id) == alert_id


def test_document_analyst_decision_task(monkeypatch):
    fake = RecordingUseCase(SimpleNamespace(object_storage_ref=SimpleNamespace(uri="s3://doc")))
    _factory(monkeypatch, tasks, "get_document_analyst_decision_use_case", fake)
    alert_id, workflow_id = str(uuid4()), str(uuid4())
    result = tasks.document_analyst_decision.run(alert_id, workflow_id, {})
    assert result["object_storage_uri"] == "s3://doc"
    assert fake.calls[0][0][0].alert_id.hex == alert_id.replace("-", "")


def test_evaluate_alert_reasoning_task(monkeypatch):
    fake = RecordingUseCase(SimpleNamespace(evaluation=None, counted=False))
    _factory(monkeypatch, tasks, "get_evaluate_alert_reasoning_use_case", fake)
    alert_id = str(uuid4())
    assert tasks.evaluate_alert_reasoning.run(alert_id, str(uuid4())) == {
        "status": "skipped", "alert_id": alert_id, "counted": False
    }


def test_execute_alert_action_task(monkeypatch):
    fake = RecordingUseCase(SimpleNamespace(action="pass", detail="done"))
    _factory(monkeypatch, tasks, "get_execute_alert_action_use_case", fake)
    result = tasks.execute_alert_action.run("pass", str(uuid4()))
    assert result["action"] == "pass"
    assert fake.calls[0][0][0].action == "pass"


def test_analyze_dataset_task(monkeypatch):
    fake = RecordingUseCase()
    operations = InMemoryOperationsRepository()
    monkeypatch.setattr(tasks, "get_analyze_dataset_use_case", lambda: fake)
    monkeypatch.setattr(tasks, "get_async_operation_repository", lambda: operations)
    assert tasks.analyze_dataset_task.run("ds", None) == {"status": "ok", "dataset_name": "ds"}
    assert fake.calls[0][0][0] == "ds"


def test_delete_dataset_task(monkeypatch):
    fake, operations = RecordingUseCase(), InMemoryOperationsRepository()
    monkeypatch.setattr(tasks, "get_delete_dataset_use_case", lambda: fake)
    monkeypatch.setattr(tasks, "get_async_operation_repository", lambda: operations)
    task_id = str(uuid4())
    assert tasks.delete_dataset_task.run("ds", task_id)["status"] == "ok"
    assert fake.calls[0][0] == ("ds",)


def test_analyze_fraud_marking_task(monkeypatch):
    @dataclass
    class Output:
        total_rows: int = 0

    fake, operations = RecordingUseCase(Output()), InMemoryOperationsRepository()
    monkeypatch.setattr(tasks, "get_analyze_fraud_marking_use_case", lambda: fake)
    monkeypatch.setattr(tasks, "get_async_operation_repository", lambda: operations)
    result = tasks.analyze_fraud_marking_task.run("ds", "a", "b", "at", "bt", ["yes"], str(uuid4()))
    assert result == {"total_rows": 0}
    assert fake.calls[0][0][0].dataset_name == "ds"


def test_train_model_task(monkeypatch):
    fake = RecordingUseCase({"status": "done"})
    import src.infrastructure.workflows.celery.model_training as training
    monkeypatch.setattr(training, "run_model_training", lambda *args, **kwargs: fake.execute(*args))
    for name in ("get_model_repository", "get_async_operation_repository", "get_dataset_repository", "get_model_storage"):
        monkeypatch.setattr(tasks, name, lambda: object())
    assert tasks.train_model_task.run("model", "operation") == {"status": "done"}


def test_preview_features_task(monkeypatch):
    fake = RecordingUseCase({"rows": []})
    _factory(monkeypatch, tasks, "get_preview_features_use_case", fake)
    assert tasks.preview_features_task.run({}, [], None) == {"rows": []}
    assert fake.calls[0][0] == ({}, [], None)


def test_parse_analyst_capacity_workbook_task(monkeypatch):
    from dataclasses import dataclass

    import src.infrastructure.entrypoint.worker.analyst_capacity_workbook as parser
    @dataclass
    class Profile:
        id: str
    monkeypatch.setattr(parser, "parse_analyst_capacity_workbook", lambda content: ([Profile("p")], {date(2025, 1, 1): "p"}))
    result = tasks.parse_analyst_capacity_workbook_task.run(base64.b64encode(b"x").decode())
    assert result == {"profiles": [{"id": "p"}], "day_overrides": {"2025-01-01": "p"}}


def test_import_fraud_label_reviews_task(monkeypatch):
    import src.infrastructure.workflows.celery.factories as factories
    from src.application.ports.fraud_label_review_import_port import (
        FraudLabelReviewImportStatus,
    )
    output = SimpleNamespace(status=FraudLabelReviewImportStatus.READY, total=0, applied=0, failed=0, error=None, rows=[])
    fake = RecordingUseCase(output)
    monkeypatch.setattr(factories, "get_import_fraud_label_reviews_use_case", lambda: fake)
    assert tasks.import_fraud_label_reviews_task.run(base64.b64encode(b"").decode(), "user")["total"] == 0


def test_reconcile_alert_rollups_task(monkeypatch):
    import src.infrastructure.workflows.celery.factories as factories
    output = SimpleNamespace(drift=0, drift_by_level={}, corrected=0, skipped_concurrent=0, rows_checked=0, days_checked=0, months_checked=0, snapshots_backfilled=0)
    fake = RecordingUseCase(output)
    monkeypatch.setattr(factories, "get_reconcile_alert_rollups_use_case", lambda: fake)
    assert tasks.reconcile_alert_rollups.run()["drift"] == 0
    assert len(fake.calls) == 1


def test_record_operational_state_task(monkeypatch):
    import src.infrastructure.workflows.celery.factories as factories
    from src.application.ports.monitoring_port import OperationalStateSnapshot
    fake = RecordingUseCase(OperationalStateSnapshot(agent_enabled=False, within_operating_hours=False, analyst_queue_depth=0, analyst_queue_oldest_age_seconds=0, analysts_available=0, voicebot_slots_available=0))
    monkeypatch.setattr(factories, "get_record_operational_state_use_case", lambda: fake)
    assert tasks.record_operational_state.run()["agent_enabled"] is False


def test_analyze_alert_schema_presence_task(monkeypatch):
    import src.infrastructure.workflows.celery.factories as factories
    fake = RecordingUseCase(None)
    monkeypatch.setattr(factories, "get_analyze_alert_schema_presence_use_case", lambda: fake)
    assert tasks.analyze_alert_schema_presence.run() is None
def test_alert_review_task_retries_transient_errors(monkeypatch):
    class FailingUseCase:
        def execute(self, *args, **kwargs):
            raise RuntimeError("transient")

    _factory(monkeypatch, tasks, "get_run_alert_review_workflow_use_case", FailingUseCase())
    with pytest.raises(RuntimeError, match="transient"):
        tasks.run_alert_review_workflow.run(str(uuid4()))
    assert tasks.run_alert_review_workflow.max_retries == tasks._ALERT_REVIEW_MAX_RETRIES
    assert Exception in tasks.run_alert_review_workflow.autoretry_for


def test_alert_review_task_does_not_retry_terminal_domain_errors(monkeypatch):
    from src.domain.alerts.exceptions import AdversarialFeedbackLimitExceededError

    class TerminalUseCase:
        def execute(self, *args, **kwargs):
            raise AdversarialFeedbackLimitExceededError("stop")

    _factory(monkeypatch, tasks, "get_run_alert_review_workflow_use_case", TerminalUseCase())
    with pytest.raises(AdversarialFeedbackLimitExceededError):
        tasks.run_alert_review_workflow.run(str(uuid4()))
    assert AdversarialFeedbackLimitExceededError in tasks.run_alert_review_workflow.dont_autoretry_for
