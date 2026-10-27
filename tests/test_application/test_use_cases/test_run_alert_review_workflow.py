from __future__ import annotations

from datetime import UTC, datetime
from types import MethodType, SimpleNamespace
from uuid import uuid4

import pytest

from src.application.dtos.adversarial_review_alert_dtos import (
    AdversarialReviewAlertOutput,
)
from src.application.dtos.workflow_run_state import WorkflowRunState
from src.application.use_cases.alerts.run_alert_review_workflow import (
    RunAlertReviewWorkflowUseCase,
)
from src.domain.alerts.entities import (
    AlertStatus,
)
from src.domain.alerts.exceptions import AdversarialFeedbackLimitExceededError
from src.domain.workflows.entities import (
    WorkflowExecutionRecord,
    WorkflowStatus,
)


class InMemoryWorkflowRepository:
    def __init__(self):
        self.updates = []

    def update(self, workflow_id, **fields):
        self.updates.append((workflow_id, fields))


class InMemoryAlertRepository:
    def __init__(self):
        self.statuses = []

    def update(self, alert_id, **fields):
        self.statuses.append((alert_id, fields))

    def get(self, alert_id):
        return SimpleNamespace(event_id="event-42")


class RecordingEscalationDispatcher:
    def __init__(self):
        self.calls = []

    def dispatch(self, **fields):
        self.calls.append(fields)


class RecordingMetricsUseCase:
    def execute(self, request):
        return None


def _workflow(max_feedback_iterations: int = 1) -> WorkflowExecutionRecord:
    now = datetime.now(UTC)
    return WorkflowExecutionRecord(
        id=uuid4(),
        alert_id=uuid4(),
        async_operation_id=uuid4(),
        workflow_name="alert_review",
        status=WorkflowStatus.RUNNING,
        input={},
        output=None,
        error=None,
        current_step=None,
        feedback_iterations=0,
        max_feedback_iterations=max_feedback_iterations,
        created_at=now,
        updated_at=now,
    )


def _harness() -> RunAlertReviewWorkflowUseCase:
    use_case = object.__new__(RunAlertReviewWorkflowUseCase)
    use_case._workflows = InMemoryWorkflowRepository()
    use_case._alerts = InMemoryAlertRepository()
    use_case._escalation = RecordingEscalationDispatcher()
    use_case._record_metrics_event = RecordingMetricsUseCase()
    use_case._workflow_span = None
    use_case._dimensions = {}
    return use_case


def test_feedback_loop_repeats_classification_until_adversarial_accepts() -> None:
    use_case = _harness()
    seen: list[str] = []
    adversarial_outputs = iter(
        [
            AdversarialReviewAlertOutput(True, "needs evidence"),
            AdversarialReviewAlertOutput(False, "accepted"),
        ]
    )

    def run_step(self, workflow, step_name, context, attempt=1):
        seen.append(step_name)
        if step_name == "adversarial":
            context[step_name] = next(adversarial_outputs)
        return context

    use_case._run_step = MethodType(run_step, use_case)
    context: WorkflowRunState = {"classification_attempt": 1}

    result = use_case._run_adversarial_review(_workflow(), context)

    assert seen == ["adversarial", "classification", "adversarial"]
    assert result["feedback_iterations"] == 1
    assert result["classification_attempt"] == 2


def test_feedback_limit_escalation_records_failure_for_human_review() -> None:
    use_case = _harness()
    use_case._run_step = MethodType(
        lambda self, workflow, step_name, context, attempt=1: context
        | {step_name: AdversarialReviewAlertOutput(True, "still inconsistent")},
        use_case,
    )
    workflow = _workflow(max_feedback_iterations=1)
    context: WorkflowRunState = {"classification_attempt": 1}

    with pytest.raises(AdversarialFeedbackLimitExceededError):
        use_case._run_adversarial_review(workflow, context)

    escalation = use_case._escalation
    use_case._escalate_to_analyst(workflow, "feedback limit reached")
    assert escalation.calls == [
        {
            "alert_id": workflow.alert_id,
            "workflow_execution_id": workflow.id,
            "event_id": "event-42",
            "session_id": None,
            "reason": "feedback limit reached",
        }
    ]
    assert use_case._alerts.statuses[-1] == (
        workflow.alert_id,
        {"status": AlertStatus.ESCALATED},
    )


@pytest.mark.parametrize("max_cycles", [0, 1])
def test_detector_feedback_limit_remains_bounded_for_invalid_reviews(max_cycles):
    use_case = _harness()
    use_case._run_step = MethodType(
        lambda self, workflow, step_name, context, attempt=1: context
        | {step_name: AdversarialReviewAlertOutput(True, "invalid review")},
        use_case,
    )
    context: WorkflowRunState = {"detector_attempt": 1}
    with pytest.raises(AdversarialFeedbackLimitExceededError):
        use_case._run_detector_adversarial_review(_workflow(max_cycles), context)
    assert context.get("detector_feedback_iterations", 0) <= max_cycles


def test_detector_correction_finishes_with_human_routing_without_another_loop():
    from src.domain.alerts.entities import AdversarialDecision

    use_case = _harness()
    reviews = iter(
        [
            AdversarialReviewAlertOutput(True, "contradictory evidence"),
            AdversarialReviewAlertOutput(
                False,
                "",
                reasoning="Uncertainty remains",
                decision=AdversarialDecision.SCALE_TO_ANALYST,
            ),
        ]
    )
    seen = []

    def run_step(self, workflow, step_name, context, attempt=1):
        seen.append((step_name, attempt))
        if step_name == "detector_adversarial":
            context[step_name] = next(reviews)
        return context

    use_case._run_step = MethodType(run_step, use_case)
    result = use_case._run_detector_adversarial_review(
        _workflow(), {"detector_attempt": 1}
    )
    assert (
        result["detector_adversarial"].decision == AdversarialDecision.SCALE_TO_ANALYST
    )
    assert seen == [
        ("detector_adversarial", 1),
        ("detector", 2),
        ("detector_adversarial", 2),
    ]
