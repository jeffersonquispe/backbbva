from __future__ import annotations

import dataclasses
import json
from typing import Any


@dataclasses.dataclass(frozen=True)
class _XGBoostScore:
    score: float
    model_id: str
    model_tag: str
    is_fraud: str  # "fraud" | "not_fraud" | "unknown" (uncertainty band)
    verdict: str
    fraud_threshold: float
    uncertainty_threshold: float
    top_features: list[dict[str, Any]] | None

    @property
    def reasoning(self) -> str:
        return f"XGBoost ({self.model_tag}) obtuvo {self.score:.4f} y {self.verdict}."

    def as_output(self) -> dict[str, Any]:
        # Kept apart from the LLM's reasoning on every step output: the
        # model's own result plus which variables weighed most (SHAP).
        return {
            "model_id": self.model_id,
            "model_tag": self.model_tag,
            "score": self.score,
            "prediction": self.is_fraud,
            "verdict": self.verdict,
            "fraud_threshold": self.fraud_threshold,
            "uncertainty_threshold": self.uncertainty_threshold,
            "top_features": self.top_features,
        }

    def prompt_block(self) -> str:
        return (
            "\n\nSalida del modelo XGBoost (evidencia separada del resto de "
            "señales; top_features son las variables con más peso en la "
            "predicción según SHAP):\n"
            + json.dumps(self.as_output(), ensure_ascii=False, default=str)
        )
