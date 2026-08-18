from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from src.application.dtos.pre_process_dtos import PreProcessAlertOutput
from src.application.dtos.profile_alert_dtos import ProfileAlertOutput

UNKNOWN = "unknown"


@dataclass
class ClassifyAlertInput:
    alert_id: UUID
    pre_process: PreProcessAlertOutput
    profile: ProfileAlertOutput


@dataclass
class ClassifyAlertOutput:
    is_fraud: str  # "fraud" | "not_fraud" | "unknown"
    fraud_classification: str  # taxonomy label, or "unknown"
    reasoning: str
    # Full Thought/Action/Observation transcript of the ReAct loop, kept
    # so downstream steps (e.g. adversarial) can inspect how the agent
    # got to its conclusion, not just the final one-line reasoning.
    cot: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
