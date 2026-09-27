from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from src.application.dtos.pre_process_dtos import PreProcessAlertOutput
from src.application.dtos.profile_alert_dtos import ProfileAlertOutput

UNKNOWN = "unknown"


@dataclass
class ClassifyAlertInput:
    alert_id: UUID
    pre_process: PreProcessAlertOutput
    profile: ProfileAlertOutput
    # Ground-truth marcacion_final from a test-run dataset row, if this
    # alert came from one (None for real, non-test alerts). Never placed
    # in the LLM prompt/context - see _alert_context - it exists purely
    # so the test-run UI can show predicted vs. expected side by side.
    expected_classification: str | None = None
    # Ground-truth "tipo" (Fraude/NoFraude) from the same dataset row - the
    # real, matured outcome, as opposed to expected_classification (the
    # analyst's contemporaneous marcacion_final call). Also never placed
    # in the LLM prompt/context; exists purely for classification_metrics.py
    # to score the model against reality, separately from agreement with
    # the analyst.
    ground_truth_tipo: str | None = None
    # Present when the Detector had a configured XGBoost model. Keeping the
    # evidence beside the detector result makes thresholds and optional SHAP
    # explanations visible in workflow history without changing the LLM API.
    model_score: float | None = None
    model_id: str | None = None
    model_top_features: list[dict[str, Any]] | None = None
    # Audit trail of bounded vector-store/history investigations performed
    # before the final detector/classification answer.
    research_delegations: list[dict[str, Any]] | None = None


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
    expected_classification: str | None = None
    ground_truth_tipo: str | None = None
