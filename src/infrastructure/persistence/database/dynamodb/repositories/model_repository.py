from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import asdict
from typing import Any
from uuid import UUID

from src.application.ports.model_port import (
    FieldTransform,
    HistoricalFeature,
    TrainingConfig,
    FieldTransformKind,
    ModelRecord,
    ModelRepository,
    ModelStatus,
)
from src.domain.models.exceptions import ModelNotFoundError
from src.infrastructure.persistence.database.dynamodb.client import (
    get_dynamodb_resource,
)
from src.infrastructure.persistence.database.dynamodb.serialization import (
    from_dynamodb,
    to_dynamodb,
)

MODELS_TABLE_NAME = "models"


class DynamoModelRepository(ModelRepository):
    def __init__(self) -> None:
        self._table = get_dynamodb_resource().Table(MODELS_TABLE_NAME)

    def create(self, model: ModelRecord) -> ModelRecord:
        self._table.put_item(Item=_to_item(model))
        return model

    def get(self, model_id: UUID) -> ModelRecord | None:
        response = self._table.get_item(Key={"model_id": str(model_id)})
        item = response.get("Item")
        if item is None:
            return None
        return _from_item(item)

    def list(self) -> list[ModelRecord]:
        response = self._table.scan()
        return [_from_item(item) for item in response.get("Items", [])]

    def get_active(self) -> ModelRecord | None:
        for model in self.list():
            if model.active:
                return model
        return None

    def update(self, model: ModelRecord) -> ModelRecord:
        model.updated_at = datetime.now(timezone.utc)
        self._table.put_item(Item=_to_item(model))
        return model

    def activate(self, model_id: UUID) -> ModelRecord:
        target = self.get(model_id)
        if target is None:
            raise ModelNotFoundError(model_id)
        for model in self.list():
            if model.id != model_id and model.active:
                model.active = False
                self.update(model)
        target.active = True
        return self.update(target)

    def delete(self, model_id: UUID) -> None:
        self._table.delete_item(Key={"model_id": str(model_id)})


def _to_item(model: ModelRecord) -> dict[str, Any]:
    return {
        "model_id": str(model.id),
        "tag": model.tag,
        "description": model.description,
        "status": model.status.value,
        "dataset_name": model.dataset_name,
        "target_field": model.target_field,
        "positive_labels": model.positive_labels,
        "feature_transforms": [
            {
                "field": t.field,
                "kind": t.kind.value,
                "reference_field": t.reference_field,
                "top_n": t.top_n,
            }
            for t in model.feature_transforms
        ],
        "active": model.active,
        "metrics": to_dynamodb(model.metrics),
        "storage_ref": model.storage_ref,
        "created_at": model.created_at.isoformat(),
        "updated_at": model.updated_at.isoformat(),
        "created_by": model.created_by,
        "error": model.error,
        "historical_features": to_dynamodb([asdict(f) for f in model.historical_features]),
        "training_config": to_dynamodb(asdict(model.training_config)),
        "training_report": to_dynamodb(model.training_report),
        "feature_configuration": to_dynamodb(model.feature_configuration),
    }


def _from_item(item: dict[str, Any]) -> ModelRecord:
    return ModelRecord(
        id=UUID(item["model_id"]),
        tag=item["tag"],
        description=item.get("description", ""),
        status=ModelStatus(item["status"]),
        dataset_name=item["dataset_name"],
        target_field=item["target_field"],
        positive_labels=list(item.get("positive_labels") or []),
        feature_transforms=[
            FieldTransform(
                field=t["field"],
                kind=FieldTransformKind(t["kind"]),
                reference_field=t.get("reference_field"),
                top_n=int(t.get("top_n", 30)),
            )
            for t in (item.get("feature_transforms") or [])
        ],
        active=bool(item.get("active", False)),
        metrics=from_dynamodb(item.get("metrics")),
        storage_ref=item.get("storage_ref"),
        created_at=datetime.fromisoformat(item["created_at"]),
        updated_at=datetime.fromisoformat(item["updated_at"]),
        created_by=item.get("created_by"),
        error=item.get("error"),
        historical_features=[HistoricalFeature(**f) for f in from_dynamodb(item.get("historical_features", []))],
        training_config=TrainingConfig(**from_dynamodb(item.get("training_config", {}))),
        training_report=from_dynamodb(item.get("training_report")),
        feature_configuration=from_dynamodb(item.get("feature_configuration")),
    )
