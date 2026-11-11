from __future__ import annotations

from typing import Any, TypedDict


class WorkflowRunState(TypedDict, total=False):
    """Shared state carried between alert review workflow steps.

    Step outputs are keyed by their registered step name. The explicit fields
    describe orchestration-owned values; step-specific outputs remain Any
    because their types differ by step.
    """

    workflow_execution_id: str
    alert_id: str
    async_operation_id: str
    input: dict[str, Any] | None
    classification_attempt: int
    detector_attempt: int
    feedback_iterations: int
    detector_feedback_iterations: int
    workflow_started_at: str
    status_reporter: Any
    raw_payload: dict[str, Any]
    current_step_id: str
    active_configuration: Any
    # step name -> the LLM it ran with (element/name/deployment/source)
    llm_resolutions: dict[str, dict[str, Any]]
    segment_code: str
    schema_comparison: Any
    agent_outputs: dict[str, Any]
    pre_process: Any
    deterministic: Any
    detector: Any
    analyst: Any
    executor: Any
    post_process: Any
    adversarial: Any
    detector_adversarial: Any
