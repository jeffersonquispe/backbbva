from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.domain.configurations.entities import (
        ConfigurationRecord,
        SegmentSettings,
        VectorStoreResearchConfig,
    )


class VectorStoreGenerationStatus(StrEnum):
    BUILDING = "building"
    READY = "ready"
    FAILED = "failed"
    # Its OpenSearch documents were deleted by the retention job; the record
    # stays for audit and so a stale pin fails with a clear reason.
    RETIRED = "retired"


@dataclass(frozen=True)
class VectorStoreManifestItem:
    asset_type: str
    asset_id: str
    asset_version: int


@dataclass(frozen=True)
class VectorStoreGeneration:
    """One immutable OpenSearch load of a vector-store instance.

    Building never edits or deletes another generation: what a test ran
    against is exactly what a deploy request publishes. Production uses the
    generation the active configuration pins, so building a new one has no
    production effect until an approved deploy request activates a
    configuration that pins it.
    """

    instance_id: str
    generation: int
    status: VectorStoreGenerationStatus
    built_by: str
    created_at: datetime
    # SHA-256 over the documents actually ingested (texts, embeddings and
    # relations): two builds of identical content share one generation.
    fingerprint: str = ""
    manifest: tuple[VectorStoreManifestItem, ...] = field(default_factory=tuple)
    document_count: int = 0
    ready_at: datetime | None = None
    retired_at: datetime | None = None
    error: str | None = None
    # Created by the one-off migration from the old single promoted
    # generation; its manifest is the instance's manifest at migration time.
    migrated: bool = False


@dataclass(frozen=True)
class VectorStorePin:
    instance_id: str
    generation: int | None


def iter_vector_store_research(
    segments: Mapping[str, SegmentSettings],
) -> Iterator[tuple[str, str, VectorStoreResearchConfig]]:
    """Every enabled vector-store research tool of a configuration's
    segments, as (segment key, step name, config). Analyst reuses
    Classification's."""
    for segment_key, segment in segments.items():
        agent = segment.agent
        for step_name, step in (
            ("detector", agent.detector),
            ("detector_adversarial", agent.detector_adversarial),
            ("classification", agent.classification),
            ("adversarial", agent.adversarial),
        ):
            research = step.delegated_research.vector_store
            if research.enabled and research.vector_store_instance_id:
                yield segment_key, step_name, research


def configuration_vector_store_pins(
    config: ConfigurationRecord,
) -> set[VectorStorePin]:
    return {
        VectorStorePin(
            research.vector_store_instance_id or "", research.vector_store_generation
        )
        for _, _, research in iter_vector_store_research(config.segments)
    }
