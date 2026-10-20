from uuid import uuid4

from src.application.ports.model_port import ModelRecord, ModelStatus
from src.infrastructure.workflows.celery.model_pipeline_evaluator import (
    StoredModelPipelineEvaluator,
)


class InMemoryModelScoringClient:
    def __init__(self):
        self.calls = []

    def score_row(self, model_id, row):
        self.calls.append((model_id, row))
        return {"predicted_positive": row["value"] > 0}


def test_pipeline_evaluator_scores_each_row_through_model_scoring_port():
    model_id = uuid4()
    model = ModelRecord(
        id=model_id,
        tag="candidate",
        description="",
        status=ModelStatus.READY,
        dataset_name="dataset",
        target_field="fraud_label",
    )
    rows = [{"value": 1}, {"value": -1}]
    scoring = InMemoryModelScoringClient()

    result = StoredModelPipelineEvaluator(scoring).predict_positive(model, rows)

    assert result == [True, False]
    assert scoring.calls == [(str(model_id), rows[0]), (str(model_id), rows[1])]
