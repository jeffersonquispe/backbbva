from __future__ import annotations

from io import BytesIO

import joblib

from src.application.ports.model_port import ModelRecord
from src.infrastructure.entrypoint.mcp.scoring import score_row


class StoredModelPipelineEvaluator:
    def __init__(self, storage) -> None:
        self._storage = storage

    def predict_positive(self, model: ModelRecord, rows: list[dict]) -> list[bool]:
        if not model.storage_ref:
            raise ValueError("Model artifact is unavailable")
        bundle = joblib.load(BytesIO(self._storage.get_bytes(model.storage_ref)))
        return [bool(score_row(bundle, row)["predicted_positive"]) for row in rows]
