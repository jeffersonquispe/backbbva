from __future__ import annotations

from src.application.ports.model_port import ModelRecord
from src.application.ports.model_scoring_port import ModelScoringPort


class StoredModelPipelineEvaluator:
    """Scores pinned models through MCP, which owns the ML runtime."""

    def __init__(self, scoring: ModelScoringPort) -> None:
        self._scoring = scoring

    def predict_positive(self, model: ModelRecord, rows: list[dict]) -> list[bool]:
        return [
            bool(self._scoring.score_row(str(model.id), row)["predicted_positive"])
            for row in rows
        ]
