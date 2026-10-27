"""One-off migration from the single "promoted" OpenSearch generation per
vector-store instance to immutable, pinned generations.

1. Every instance row that still carries the legacy ``promoted_version``
   gets a READY generation record with that number (``migrated=True``). Its
   documents are already in OpenSearch; only the record is new. Its
   fingerprint stays empty: the documents were loaded from the manifest as
   it was at promotion time, which may differ from today's, so a later
   build of the current manifest never reuses it by mistake. The legacy
   attributes are then removed from the instance row.
2. Every saved configuration segment whose vector-store research tool
   names an instance but no generation is pinned to that instance's
   promoted generation - the documents it was already searching.

Idempotent: re-running skips existing records and pinned tools. With
``dry_run`` nothing is written; the report lists what would change."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from botocore.exceptions import ClientError
from opensearchpy import OpenSearch

from src.application.errors import ConflictError
from src.application.ports.vector_store_generation_port import (
    VectorStoreGeneration,
    VectorStoreGenerationRepository,
    VectorStoreGenerationStatus,
    VectorStoreManifestItem,
)
from src.application.ports.vector_store_instance_port import (
    VectorStoreInstanceRepository,
)
from src.infrastructure.persistence.database.dynamodb.client import (
    get_dynamodb_resource,
)
from src.infrastructure.persistence.database.dynamodb.manager import create_table
from src.infrastructure.persistence.database.dynamodb.repositories.configuration_repository import (
    SEGMENTS_TABLE_NAME,
)
from src.infrastructure.persistence.database.dynamodb.repositories.vector_store_instance_repository import (
    VECTOR_STORE_INSTANCES_TABLE_NAME,
)
from src.infrastructure.persistence.database.dynamodb.schemas import (
    VECTOR_STORE_GENERATIONS_TABLE,
)
from src.infrastructure.persistence.vector_store.opensearch.index import (
    FRAUD_KNOWLEDGE_INDEX,
)

_STEPS = ("detector", "detector_adversarial", "classification", "adversarial")
_LEGACY_ATTRIBUTES = ("promoted_version", "promoted_at", "promoted_by")


@dataclass
class VectorStoreGenerationMigrationReport:
    dry_run: bool
    generations_created: list[str] = field(default_factory=list)
    generations_existing: list[str] = field(default_factory=list)
    instances_never_promoted: list[str] = field(default_factory=list)
    segment_tools_pinned: list[str] = field(default_factory=list)
    segment_tools_unresolved: list[str] = field(default_factory=list)


class VectorStoreGenerationMigration:
    def __init__(
        self,
        *,
        instances: VectorStoreInstanceRepository,
        generations: VectorStoreGenerationRepository,
        opensearch: OpenSearch,
    ) -> None:
        resource = get_dynamodb_resource()
        self._instance_table = resource.Table(VECTOR_STORE_INSTANCES_TABLE_NAME)
        self._segments_table = resource.Table(SEGMENTS_TABLE_NAME)
        self._instances = instances
        self._generations = generations
        self._opensearch = opensearch

    def run(self, *, dry_run: bool) -> VectorStoreGenerationMigrationReport:
        report = VectorStoreGenerationMigrationReport(dry_run=dry_run)
        if not dry_run:
            create_table(VECTOR_STORE_GENERATIONS_TABLE)
        try:
            existing = self._generations.list()
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") != "ResourceNotFoundException" or not dry_run:
                raise
            existing = []
        self._existing = {(g.instance_id, g.generation): g for g in existing}
        promoted = self._migrate_instances(report, dry_run=dry_run)
        self._pin_segments(promoted, report, dry_run=dry_run)
        return report

    def _migrate_instances(
        self, report: VectorStoreGenerationMigrationReport, *, dry_run: bool
    ) -> dict[str, int]:
        promoted: dict[str, int] = {}
        for item in _scan(self._instance_table):
            instance_id = item["id"]
            if item.get("promoted_version") is None:
                # Already migrated rows have no legacy attribute; their
                # generations are already records.
                if not self._ready_generations(instance_id):
                    report.instances_never_promoted.append(instance_id)
                continue
            number = int(item["promoted_version"])
            promoted[instance_id] = number
            label = f"{instance_id}@g{number}"
            if (instance_id, number) in self._existing:
                report.generations_existing.append(label)
            else:
                report.generations_created.append(label)
                if not dry_run:
                    self._create_generation(instance_id, number, item)
            if not dry_run:
                self._instance_table.update_item(
                    Key={"id": instance_id},
                    UpdateExpression="REMOVE " + ", ".join(_LEGACY_ATTRIBUTES),
                )
        for generation in sorted(self._existing.values(), key=lambda g: g.generation, reverse=True):
            if generation.status == VectorStoreGenerationStatus.READY:
                promoted.setdefault(generation.instance_id, generation.generation)
        return promoted

    def _create_generation(
        self, instance_id: str, number: int, item: dict[str, Any]
    ) -> None:
        promoted_at = (
            datetime.fromisoformat(item["promoted_at"])
            if item.get("promoted_at")
            else datetime.now(UTC)
        )
        count = self._opensearch.count(
            index=FRAUD_KNOWLEDGE_INDEX,
            body={
                "query": {
                    "bool": {
                        "filter": [
                            {"term": {"vector_store_id": instance_id}},
                            {"term": {"vector_store_version": number}},
                        ]
                    }
                }
            },
        )["count"]
        try:
            self._generations.create(
                VectorStoreGeneration(
                    instance_id=instance_id,
                    generation=number,
                    status=VectorStoreGenerationStatus.READY,
                    built_by=item.get("promoted_by") or "migración",
                    created_at=promoted_at,
                    ready_at=promoted_at,
                    fingerprint="",
                    manifest=tuple(
                        VectorStoreManifestItem(
                            asset_type=asset.asset_type.value,
                            asset_id=asset.asset_id,
                            asset_version=asset.asset_version,
                        )
                        for asset in self._instances.list_assets(instance_id)
                    ),
                    document_count=int(count),
                    migrated=True,
                )
            )
        except ConflictError:
            pass

    def _pin_segments(
        self,
        promoted: dict[str, int],
        report: VectorStoreGenerationMigrationReport,
        *,
        dry_run: bool,
    ) -> None:
        for item in _scan(self._segments_table):
            agent = item.get("agent") or {}
            changed = False
            for step in _STEPS:
                research = (
                    ((agent.get(step) or {}).get("delegated_research") or {}).get(
                        "vector_store"
                    )
                    or {}
                )
                instance_id = research.get("vector_store_instance_id")
                if (
                    not research.get("enabled")
                    or not instance_id
                    or research.get("vector_store_generation") is not None
                ):
                    continue
                label = f"{item['config_key']}:{item.get('segment_code')}:{step}"
                generation = promoted.get(instance_id)
                if generation is None:
                    report.segment_tools_unresolved.append(f"{label} -> {instance_id}")
                    continue
                research["vector_store_generation"] = generation
                report.segment_tools_pinned.append(f"{label} -> {instance_id}@g{generation}")
                changed = True
            if changed and not dry_run:
                self._segments_table.update_item(
                    Key={"config_key": item["config_key"], "id": item["id"]},
                    UpdateExpression="SET #agent = :agent",
                    ExpressionAttributeNames={"#agent": "agent"},
                    ExpressionAttributeValues={":agent": agent},
                )

    def _ready_generations(self, instance_id: str) -> bool:
        return any(
            item.status == VectorStoreGenerationStatus.READY
            for item in self._generations.list(instance_id)
        )


def _scan(table) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    kwargs: dict[str, Any] = {}
    while True:
        response = table.scan(**kwargs)
        items.extend(response.get("Items", []))
        if "LastEvaluatedKey" not in response:
            return items
        kwargs = {"ExclusiveStartKey": response["LastEvaluatedKey"]}
