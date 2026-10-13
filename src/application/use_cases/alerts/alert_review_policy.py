from __future__ import annotations

import dataclasses
from typing import Any

from src.application.dtos.adversarial_review_alert_dtos import (
    AdversarialReviewAlertOutput,
)
from src.application.dtos.workflow_run_state import WorkflowRunState
from src.domain.configurations.entities import (
    SegmentSettings,
)
from src.domain.workflows.entities import (
    WorkflowExecutionRecord,
)

LINEAR_STEPS = (
    "pre_process",
    "deterministic",
    "profiling",
    "detector",
    "detector_adversarial",
    "classification",
    "adversarial",
    "analyst",
    "executor",
    "post_process",
)

# Steps whose output feeds the analyst-decision documenter.
DOCUMENTED_STEPS = (
    "pre_process",
    "profiling",
    "classification",
    "adversarial",
    "analyst",
)


def active_segment(context: WorkflowRunState) -> SegmentSettings | None:
    config = context.get("active_configuration")
    code = context.get("segment_code")
    if config is None or code is None:
        return None
    segment = config.segments.get(code)
    return segment if segment is not None and segment.enabled else None


def effective_max_feedback_iterations(
    workflow: WorkflowExecutionRecord, context: WorkflowRunState
) -> int:
    segment = active_segment(context)
    if segment is not None:
        return segment.agent.adversarial.max_cycles
    return workflow.max_feedback_iterations


def effective_max_detector_feedback_iterations(
    workflow: WorkflowExecutionRecord, context: WorkflowRunState
) -> int:
    segment = active_segment(context)
    if segment is not None:
        return segment.agent.detector_adversarial.max_cycles
    return workflow.max_feedback_iterations


def needs_classification_feedback(
    context: WorkflowRunState, max_feedback_iterations: int
) -> bool:
    adversarial: AdversarialReviewAlertOutput | None = context.get("adversarial")
    return bool(
        adversarial is not None
        and adversarial.requires_classification_feedback
        and context.get("feedback_iterations", 0) < max_feedback_iterations
    )


def needs_detector_feedback(
    context: WorkflowRunState, max_feedback_iterations: int
) -> bool:
    detector_adversarial: AdversarialReviewAlertOutput | None = context.get(
        "detector_adversarial"
    )
    return bool(
        detector_adversarial is not None
        and detector_adversarial.requires_classification_feedback
        and context.get("detector_feedback_iterations", 0) < max_feedback_iterations
    )


def output_as_dict(output: Any) -> Any:
    """A step output as persisted: dataclasses flattened, dicts as-is."""
    if dataclasses.is_dataclass(output) and not isinstance(output, type):
        return dataclasses.asdict(output)
    return output


def context_steps_snapshot(context: WorkflowRunState) -> dict[str, dict[str, Any]]:
    snapshot: dict[str, dict[str, Any]] = {}
    for step_name in DOCUMENTED_STEPS:
        output = context.get(step_name)
        if output is None:
            continue
        snapshot[step_name] = output_as_dict(output)
    return snapshot


def step_input(context: WorkflowRunState) -> dict[str, Any]:
    return {
        "alert_id": context["alert_id"],
        "classification_attempt": context.get("classification_attempt", 1),
    }


def relative_value(output: Any, location: str) -> Any:
    value = output
    for part in location.split("."):
        if isinstance(value, list):
            value = value[0] if value else None
        if value is None:
            return None
        if isinstance(value, dict):
            value = value.get(part)
        else:
            value = getattr(value, part, None)
    return value
