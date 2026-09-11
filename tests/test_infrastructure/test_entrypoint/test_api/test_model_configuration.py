from dataclasses import asdict
from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.application.ports.model_port import ModelRecord, ModelStatus, HistoricalFeature, TrainingConfig
from src.infrastructure.entrypoint.api.schemas import CreateModelRequest, ModelResponse
from src.application.use_cases.models.create_model import _to_output
from src.infrastructure.persistence.database.dynamodb.repositories.model_repository import _to_item, _from_item


def valid_request():
    return dict(tag="history-v1", dataset_name="sample", target_field="label", positive_labels=["risk"],
                historical_features=[dict(name="count_24h")], training_config=dict(max_depth=3, timezone="America/Bogota"))


def test_model_contract_round_trip_and_legacy_defaults():
    record = ModelRecord(id=uuid4(),tag="v1",description="",status=ModelStatus.DRAFT,dataset_name="sample",target_field="label",
                         positive_labels=["risk"],historical_features=[HistoricalFeature(name="count_24h")],
                         training_config=TrainingConfig(max_depth=3,learning_rate=.02),training_report={"thresholds":[{"threshold":.35}]})
    decoded = _from_item(_to_item(record))
    assert asdict(decoded) == asdict(record)
    response = ModelResponse.model_validate(asdict(_to_output(decoded)))
    assert response.training_config.learning_rate == .02
    old = _to_item(record)
    for k in ("historical_features","training_config","training_report"): old.pop(k)
    assert _from_item(old).training_config.n_estimators == 400


@pytest.mark.parametrize("patch",[
    {"positive_labels":[]}, {"training_config":{"max_depth":999}}, {"training_config":{"timezone":"not/a/zone"}},
    {"historical_features":[{"name":"bad name"}]},
    {"historical_features":[{"name":"count", "reference_field":"label"}]},
    {"historical_features":[{"name":"count","filter_field":"canal"}]},
    {"historical_features":[{"name":"same"},{"name":"same"}]},
    {"feature_transforms":[{"field":"label","kind":"numeric"}]},
])
def test_model_contract_rejects_invalid_recipes(patch):
    with pytest.raises(ValidationError): CreateModelRequest(**{**valid_request(),**patch})


def test_accepts_history_only_model():
    parsed=CreateModelRequest(**valid_request())
    assert parsed.training_config.max_depth == 3
    assert parsed.historical_features[0].operation == "count"
