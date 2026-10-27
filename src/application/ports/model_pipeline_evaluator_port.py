from __future__ import annotations

from typing import Protocol

from src.application.ports.model_port import ModelRecord


class ModelPipelineEvaluator(Protocol):
    def predict_positive(self, model: ModelRecord, rows: list[dict]) -> list[bool]: ...
