from __future__ import annotations

from typing import Any

from src.application.ports.dataset_analysis_port import (
    DatasetSampleRecord,
    DatasetSampleRepository,
)
from src.infrastructure.persistence.database.dynamodb.client import (
    get_dynamodb_resource,
)

DATASET_SAMPLES_TABLE_NAME = "dataset_samples"


class DynamoDatasetSampleRepository(DatasetSampleRepository):
    def __init__(self) -> None:
        self._table = get_dynamodb_resource().Table(DATASET_SAMPLES_TABLE_NAME)

    def create_batch(self, samples: list[DatasetSampleRecord]) -> None:
        with self._table.batch_writer() as batch:
            for sample in samples:
                batch.put_item(Item=_to_item(sample))

    def list_by_dataset(self, dataset_name: str) -> list[DatasetSampleRecord]:
        items: list[dict[str, Any]] = []
        kwargs: dict[str, Any] = {
            "KeyConditionExpression": "dataset_name = :dataset_name",
            "ExpressionAttributeValues": {":dataset_name": dataset_name},
        }
        while True:
            response = self._table.query(**kwargs)
            items.extend(response.get("Items", []))
            last_key = response.get("LastEvaluatedKey")
            if not last_key:
                break
            kwargs["ExclusiveStartKey"] = last_key
        return [_from_item(item) for item in items]

    def delete_by_dataset(self, dataset_name: str) -> None:
        with self._table.batch_writer() as batch:
            kwargs: dict[str, Any] = {
                "KeyConditionExpression": "dataset_name = :dataset_name",
                "ExpressionAttributeValues": {":dataset_name": dataset_name},
                # Deleting does not need the sample payload.  Projecting just
                # the keys keeps legacy datasets with many samples bounded.
                "ProjectionExpression": "dataset_name, sample_id",
            }
            while True:
                response = self._table.query(**kwargs)
                for item in response.get("Items", []):
                    batch.delete_item(
                        Key={
                            "dataset_name": item["dataset_name"],
                            "sample_id": item["sample_id"],
                        }
                    )
                last_key = response.get("LastEvaluatedKey")
                if not last_key:
                    break
                kwargs["ExclusiveStartKey"] = last_key


def _to_item(sample: DatasetSampleRecord) -> dict[str, Any]:
    return {
        "dataset_name": sample.dataset_name,
        "sample_id": sample.sample_id,
        "razon_marcacion": sample.razon_marcacion,
        "marcacion_final": sample.marcacion_final,
        "integration_point": sample.integration_point,
        "tipo": sample.tipo,
        "triggered_rules": sample.triggered_rules,
    }


def _from_item(item: dict[str, Any]) -> DatasetSampleRecord:
    return DatasetSampleRecord(
        dataset_name=item["dataset_name"],
        sample_id=item["sample_id"],
        razon_marcacion=item.get("razon_marcacion"),
        marcacion_final=item.get("marcacion_final"),
        integration_point=item.get("integration_point"),
        tipo=item.get("tipo"),
        triggered_rules=item.get("triggered_rules"),
    )
