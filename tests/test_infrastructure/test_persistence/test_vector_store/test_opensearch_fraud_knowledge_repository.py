from __future__ import annotations

import os

os.environ.setdefault("GENAI_ENVIRONMENT", "test")

from src.infrastructure.persistence.vector_store.opensearch import repository as module
from src.infrastructure.persistence.vector_store.opensearch.repository import (
    OpenSearchFraudKnowledgeRepository,
)


class RecordingOpenSearchClient:
    def __init__(self, deleted: int) -> None:
        self._deleted = deleted
        self.calls: list[dict] = []

    def delete_by_query(self, *, index, body, params):
        self.calls.append({"index": index, "body": body, "params": params})
        return {"deleted": self._deleted}


def test_delete_generation_touches_only_that_instance_generation(monkeypatch) -> None:
    audits: list[tuple] = []
    monkeypatch.setattr(module, "record_audit", lambda *args, **kwargs: audits.append(args))
    client = RecordingOpenSearchClient(deleted=12)
    repository = OpenSearchFraudKnowledgeRepository(client)

    deleted = repository.delete_generation("vector-store-v4", 3)

    assert deleted == 12
    (call,) = client.calls
    # Both terms are mandatory filters: every other generation of this
    # instance, and every other instance, keeps its documents.
    assert call["body"] == {
        "query": {
            "bool": {
                "filter": [
                    {"term": {"vector_store_id": "vector-store-v4"}},
                    {"term": {"vector_store_version": 3}},
                ]
            }
        }
    }
    assert call["params"]["refresh"] == "true"
    assert audits == [
        ("opensearch.delete_generation", module.FRAUD_KNOWLEDGE_INDEX, "vector-store-v4@3")
    ]
