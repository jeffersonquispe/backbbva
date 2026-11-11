"""The evaluator's Celery tasks: they run on its own queue and a failure ends in
the evaluator's job, never in the alert."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from celery.exceptions import Retry

from src.infrastructure.core.config import genai_config
from src.infrastructure.entrypoint.worker.celery import tasks
from src.infrastructure.queues.celery import (
    reasoning_evaluation_dispatcher as dispatchers,
)
from src.infrastructure.queues.celery.app import app

ALERT, WORKFLOW = str(uuid4()), str(uuid4())


class RecordingEvaluate:
    def __init__(self, error: Exception | None = None) -> None:
        self.error, self.failed = error, []

    def execute(self, input):
        if self.error:
            raise self.error
        return SimpleNamespace(
            evaluation=SimpleNamespace(status=SimpleNamespace(value="evaluated")),
            counted=True,
        )

    def fail(self, alert_id, code) -> None:
        self.failed.append((alert_id, code))


def _run(monkeypatch, evaluate, retries: int = 0):
    monkeypatch.setattr(
        tasks, "get_evaluate_alert_reasoning_use_case", lambda: evaluate
    )
    tasks.evaluate_alert_reasoning.push_request(retries=retries, called_directly=False)
    try:
        return tasks.evaluate_alert_reasoning.run(ALERT, WORKFLOW)
    finally:
        tasks.evaluate_alert_reasoning.pop_request()


def test_a_successful_evaluation_reports_the_verdict(monkeypatch) -> None:
    assert _run(monkeypatch, RecordingEvaluate()) == {
        "status": "evaluated",
        "alert_id": ALERT,
        "counted": True,
    }


def test_a_provider_error_is_retried_with_backoff_and_leaves_the_job_alone(
    monkeypatch,
) -> None:
    evaluate = RecordingEvaluate(ConnectionError("provider down"))
    retries: list[dict] = []

    def record_retry(**kwargs):
        retries.append(kwargs)
        raise Retry()

    monkeypatch.setattr(tasks.evaluate_alert_reasoning, "retry", record_retry)

    with pytest.raises(Retry):
        _run(monkeypatch, evaluate, retries=1)

    assert evaluate.failed == []
    assert retries[0]["countdown"] == 20 and retries[0]["max_retries"] == 3


def test_after_the_last_retry_the_job_is_closed_as_failed_and_nothing_raises(
    monkeypatch,
) -> None:
    evaluate = RecordingEvaluate(ConnectionError("provider down"))

    result = _run(monkeypatch, evaluate, retries=3)

    assert result["status"] == "failed"
    assert [code for _, code in evaluate.failed] == ["EVALUATION_FAILED"]


def test_the_request_task_only_opens_the_evaluators_job(monkeypatch) -> None:
    calls = []

    class Request:
        def execute(self, alert_id, workflow_id):
            calls.append((str(alert_id), str(workflow_id)))
            return SimpleNamespace(outcome=SimpleNamespace(value="queued"))

    monkeypatch.setattr(
        tasks, "get_request_reasoning_evaluation_use_case", lambda: Request()
    )

    assert tasks.request_reasoning_evaluation.run(ALERT, WORKFLOW) == {
        "outcome": "queued",
        "alert_id": ALERT,
    }
    assert calls == [(ALERT, WORKFLOW)]


def test_the_alert_flow_and_the_evaluator_both_publish_to_the_evaluation_queue(
    monkeypatch,
) -> None:
    sent = []
    monkeypatch.setattr(
        app,
        "send_task",
        lambda name, **kw: sent.append((name, kw["queue"])) or SimpleNamespace(id="x"),
    )

    dispatchers.CeleryReasoningEvaluationDispatcher().dispatch(uuid4(), uuid4())
    dispatchers.CeleryReasoningEvaluationJobDispatcher().enqueue(uuid4(), uuid4())

    queue = genai_config.CELERY_REASONING_EVALUATION_QUEUE
    assert sent == [
        ("metrics.request_reasoning_evaluation", queue),
        ("metrics.evaluate_alert_reasoning", queue),
    ]
    assert queue != genai_config.CELERY_DEFAULT_QUEUE


def test_the_recovery_sweep_is_scheduled_on_the_evaluation_queue() -> None:
    entry = app.conf.beat_schedule["recover-reasoning-evaluations"]

    assert entry["task"] == "metrics.recover_reasoning_evaluations"
    assert entry["options"]["queue"] == genai_config.CELERY_REASONING_EVALUATION_QUEUE
    assert entry["task"] in app.tasks
