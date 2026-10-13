from __future__ import annotations

from typing import Any

from src.application.ports.alert_review_step_executor_port import (
    AlertReviewStepExecutor,
)
from src.infrastructure.workflows.celery.review_action_steps import (
    _run_analyst,
    _run_executor,
    _run_post_process,
)
from src.infrastructure.workflows.celery.review_agent_steps import (
    _run_adversarial,
    _run_classification,
    _run_detector,
    _run_detector_adversarial,
)
from src.infrastructure.workflows.celery.review_intake_steps import (
    _resolve_segment,
    _run_deterministic,
    _run_pre_process,
    _run_profiling,
    _run_rubrics,
)

# Placeholder-era name kept for the step table: each entry composes the
# step's use case(s) from the worker factories and runs it.
_STEP_RUNNERS = {
    "pre_process": _run_pre_process,
    "deterministic": _run_deterministic,
    "profiling": _run_profiling,
    "detector": _run_detector,
    "detector_adversarial": _run_detector_adversarial,
    "classification": _run_classification,
    "adversarial": _run_adversarial,
    "analyst": _run_analyst,
    "executor": _run_executor,
    "post_process": _run_post_process,
}


class CeleryWorkerStepExecutor(AlertReviewStepExecutor):
    """Worker-side step executor: wires each step to its use case through
    ``workflows/celery/factories.py``."""

    def execute(self, step_name: str, context: dict[str, Any]) -> Any:
        runner = _STEP_RUNNERS.get(step_name)
        if runner is None:
            raise ValueError(f"Unsupported workflow step: {step_name}")
        return runner(context)

    def enrich(self, step_name: str, context: dict[str, Any]) -> dict[str, Any]:
        if step_name == "pre_process":
            return _resolve_segment(context)
        if step_name == "profiling":
            # Rubrics are part of profiling context, rather than a public
            # workflow stage.  This preserves the workflow contract while
            # making their evidence available to the Detector immediately
            # afterwards.
            context["rubrics"] = _run_rubrics(context)
        return context
