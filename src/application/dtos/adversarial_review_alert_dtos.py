from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from src.application.dtos.classify_alert_dtos import ClassifyAlertOutput
from src.application.dtos.pre_process_dtos import PreProcessAlertOutput
from src.application.dtos.profile_alert_dtos import ProfileAlertOutput


@dataclass
class AdversarialReviewAlertInput:
    alert_id: UUID
    pre_process: PreProcessAlertOutput
    profile: ProfileAlertOutput
    classification: ClassifyAlertOutput


@dataclass
class AdversarialReviewAlertOutput:
    requires_classification_feedback: bool
    feedback: str
    weak_points: list[str] = field(default_factory=list)
    reasoning: str = ""
    # Full Thought/Action/Observation transcript of the adversarial's own
    # ReAct loop, kept for the same reason classification.cot is kept.
    cot: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    # Same separate-evidence fields as ClassifyAlertOutput.
    model_output: dict[str, Any] | None = None
    research_delegations: list[dict[str, Any]] | None = None
    vector_store_interactions: list[dict[str, Any]] | None = None
