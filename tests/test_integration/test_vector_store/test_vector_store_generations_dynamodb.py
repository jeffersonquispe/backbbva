"""Generation repository and the one-off migration against a real DynamoDB
Local. Point DYNAMO_ENDPOINT at a THROWAWAY instance (table names have no
prefix), e.g. ``make metrics-loadtest-up`` then
``DYNAMO_ENDPOINT=http://localhost:8012 ... pytest -m docker_integration``."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

import pytest

if not os.getenv("DYNAMO_ENDPOINT"):
    pytest.skip(
        "Requires a throwaway DynamoDB Local (DYNAMO_ENDPOINT)",
        allow_module_level=True,
    )

from src.application.errors import ConflictError
from src.domain.fraud_knowledge.vector_store_generations import (
    VectorStoreGeneration,
    VectorStoreGenerationStatus,
)
from src.infrastructure.persistence.database.dynamodb.client import (
    get_dynamodb_resource,
)
from src.infrastructure.persistence.database.dynamodb.manager import ensure_all_tables
from src.infrastructure.persistence.database.dynamodb.repositories.configuration_repository import (
    SEGMENTS_TABLE_NAME,
)
from src.infrastructure.persistence.database.dynamodb.repositories.vector_store_generation_repository import (
    DynamoVectorStoreGenerationRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.vector_store_instance_repository import (
    VECTOR_STORE_INSTANCES_TABLE_NAME,
    DynamoVectorStoreInstanceRepository,
)
from src.infrastructure.persistence.database.dynamodb.vector_store_generation_migration import (
    VectorStoreGenerationMigration,
)

pytestmark = pytest.mark.docker_integration


class RecordingOpenSearchCount:
    """Only ``count`` is used by the migration: it records each query."""

    def __init__(self, count: int) -> None:
        self._count = count
        self.queries: list[dict] = []

    def count(self, *, index: str, body: dict) -> dict:
        self.queries.append(body)
        return {"count": self._count}


@pytest.fixture(scope="module", autouse=True)
def _tables() -> None:
    ensure_all_tables()


def _generation(instance_id: str, number: int) -> VectorStoreGeneration:
    return VectorStoreGeneration(
        instance_id=instance_id,
        generation=number,
        status=VectorStoreGenerationStatus.READY,
        built_by="qa",
        created_at=datetime(2026, 10, 1, tzinfo=UTC),
        fingerprint=f"fp-{number}",
    )


def test_generation_numbers_are_unique_and_listed_in_order() -> None:
    repo = DynamoVectorStoreGenerationRepository()
    instance_id = f"vs-{uuid.uuid4()}"
    for number in (2, 1, 3):
        repo.create(_generation(instance_id, number))

    with pytest.raises(ConflictError):
        repo.create(_generation(instance_id, 2))
    assert [item.generation for item in repo.list(instance_id)] == [1, 2, 3]
    assert repo.get(instance_id, 3).fingerprint == "fp-3"
    assert repo.get(instance_id, 9) is None


def _legacy_instance(instance_id: str, promoted_version: int) -> None:
    get_dynamodb_resource().Table(VECTOR_STORE_INSTANCES_TABLE_NAME).put_item(
        Item={
            "id": instance_id,
            "version": 99,
            "name": instance_id,
            "description": "",
            "created_at": "2026-09-01T00:00:00+00:00",
            "created_by": "qa",
            "promoted_version": promoted_version,
            "promoted_at": "2026-09-02T00:00:00+00:00",
            "promoted_by": "Andrea",
        }
    )


def _segment_with_unpinned_tool(config_key: str, instance_id: str) -> str:
    segment_id = str(uuid.uuid4())
    get_dynamodb_resource().Table(SEGMENTS_TABLE_NAME).put_item(
        Item={
            "config_key": config_key,
            "id": segment_id,
            "segment_code": "tarjetas",
            "agent": {
                "classification": {
                    "delegated_research": {
                        "vector_store": {
                            "enabled": True,
                            "vector_store_instance_id": instance_id,
                        }
                    }
                },
                "detector": {
                    "delegated_research": {
                        "vector_store": {
                            "enabled": True,
                            "vector_store_instance_id": "vs-missing-instance",
                        }
                    }
                },
            },
        }
    )
    return segment_id


def _tool(config_key: str, segment_id: str, step: str) -> dict:
    item = get_dynamodb_resource().Table(SEGMENTS_TABLE_NAME).get_item(
        Key={"config_key": config_key, "id": segment_id}
    )["Item"]
    return item["agent"][step]["delegated_research"]["vector_store"]


def test_migration_pins_saved_tools_to_the_promoted_generation_idempotently() -> None:
    instance_id = f"vs-{uuid.uuid4()}"
    config_key = f"cfg-{uuid.uuid4()}#1"
    _legacy_instance(instance_id, promoted_version=7)
    segment_id = _segment_with_unpinned_tool(config_key, instance_id)
    generations = DynamoVectorStoreGenerationRepository()
    opensearch = RecordingOpenSearchCount(count=12)

    def migration() -> VectorStoreGenerationMigration:
        return VectorStoreGenerationMigration(
            instances=DynamoVectorStoreInstanceRepository(),
            generations=generations,
            opensearch=opensearch,
        )

    dry = migration().run(dry_run=True)
    assert f"{instance_id}@g7" in dry.generations_created
    assert any(f"{instance_id}@g7" in line for line in dry.segment_tools_pinned)
    assert generations.get(instance_id, 7) is None
    assert "vector_store_generation" not in _tool(config_key, segment_id, "classification")

    applied = migration().run(dry_run=False)
    record = generations.get(instance_id, 7)
    assert record is not None
    assert (record.status, record.migrated, record.document_count, record.fingerprint) == (
        VectorStoreGenerationStatus.READY,
        True,
        12,
        "",
    )
    assert record.built_by == "Andrea"
    assert int(_tool(config_key, segment_id, "classification")["vector_store_generation"]) == 7
    # A tool naming an instance with no generation is reported, never guessed.
    assert any("vs-missing-instance" in line for line in applied.segment_tools_unresolved)
    assert "vector_store_generation" not in _tool(config_key, segment_id, "detector")
    legacy = get_dynamodb_resource().Table(VECTOR_STORE_INSTANCES_TABLE_NAME).get_item(
        Key={"id": instance_id}
    )["Item"]
    assert not {"promoted_version", "promoted_at", "promoted_by"} & set(legacy)

    again = migration().run(dry_run=False)
    assert f"{instance_id}@g7" not in again.generations_created
    assert not any(instance_id in line for line in again.segment_tools_pinned)
    assert [item.generation for item in generations.list(instance_id)] == [7]


def test_saved_pins_are_listed_without_hydrating_versions() -> None:
    from src.domain.configurations.entities import (
        ConfigurationRecord,
        GeneralSettings,
        InfraSettings,
        TestSettings,
        default_segments,
    )
    from src.domain.fraud_knowledge.vector_store_generations import VectorStorePin
    from src.infrastructure.persistence.database.dynamodb.repositories.configuration_repository import (
        DynamoConfigurationRepository,
    )

    segments = default_segments()
    research = segments["tarjetas"].agent.classification.delegated_research.vector_store
    research.enabled = True
    research.vector_store_instance_id = "vs-pins"
    research.vector_store_generation = 4
    now = datetime(2026, 10, 27, tzinfo=UTC)
    configuration_id = str(uuid.uuid4())
    repository = DynamoConfigurationRepository()
    repository.create(
        ConfigurationRecord(
            configuration_id=configuration_id,
            version=12,
            name="pins",
            description="",
            active=False,
            general=GeneralSettings(),
            infra=InfraSettings(),
            test=TestSettings(),
            created_at=now,
            updated_at=now,
            segments=segments,
        )
    )

    pins = repository.list_vector_store_pins()

    assert pins[(configuration_id, 12)] == {VectorStorePin("vs-pins", 4)}
    # The summary rows really do not carry segments: that is why this exists.
    summary = next(
        item
        for item in repository.list_all_versions()
        if item.configuration_id == configuration_id
    )
    assert not any(
        segment.agent.classification.delegated_research.vector_store.enabled
        for segment in summary.segments.values()
    )
