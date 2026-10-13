from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol


class KnowledgeAssetType(StrEnum):
    TAXONOMY = "taxonomy"
    MODUS_OPERANDI = "modus_operandi"
    YELLOW_FLAG = "yellow_flag"
    RED_FLAG = "red_flag"
    SIMILAR_CASE = "similar_case"


@dataclass(frozen=True)
class VectorStoreInstance:
    """An immutable, numbered view of the knowledge-base assets.

    The assets themselves remain independently editable.  A relation stores
    the exact asset revision included in an instance, so ``v1`` can never be
    silently changed by a later library edit.
    """

    id: str
    version: int
    name: str
    description: str
    created_at: datetime
    created_by: str
    updated_at: datetime | None = None
    updated_by: str | None = None
    # Promotion (OpenSearch) generation tracking, distinct from `version`
    # above (the Dynamo-side asset-manifest version). None means this
    # instance has never been promoted - still a draft, search must refuse
    # it (see SearchFraudKnowledgeUseCase). Each promotion increments this
    # and stamps every document it loads with the new value
    # (vector_store_version on fraud_knowledge_port.py's documents), so a
    # search always resolves to exactly the generation currently "up".
    promoted_version: int | None = None
    promoted_at: datetime | None = None
    promoted_by: str | None = None


@dataclass(frozen=True)
class VectorStoreInstanceAsset:
    vector_store_instance_id: str
    asset_type: KnowledgeAssetType
    asset_id: str
    asset_version: int
    # Copied from the source Library entry's cached embedding when attached
    # to an instance (see KnowledgeGraphService.attach) - recycled at
    # promotion time instead of re-embedding. None only for an asset
    # attached before its Library entry ever had one computed (stale data,
    # not the expected path); PromoteVectorStoreInstanceUseCase re-embeds as
    # a fallback for those.
    embedding: list[float] | None = None
    # Relation provenance makes cascading changes explainable and prevents a
    # child manually added by an analyst from being confused with a child
    # inherited from a taxonomy/MO selection.
    origin: str = "manual"
    root_asset_type: KnowledgeAssetType | None = None
    root_asset_id: str | None = None
    follow_source_updates: bool = True

    @property
    def relation_id(self) -> str:
        # The relation is addressed by the *vector-store* version, not by
        # the source asset revision (an unchanged asset at revision 1 may be
        # correctly included in vector-store v2, v3, ...).
        version_label = self.vector_store_instance_id.removeprefix("vector-store-")
        return f"{version_label}:{self.asset_type}:{self.asset_id}"


class VectorStoreInstanceRepository(Protocol):
    def create(
        self,
        instance: VectorStoreInstance,
        assets: list[VectorStoreInstanceAsset],
    ) -> VectorStoreInstance: ...

    def list(self) -> list[VectorStoreInstance]: ...

    def get(self, instance_id: str) -> VectorStoreInstance | None: ...

    def update(self, instance: VectorStoreInstance) -> VectorStoreInstance: ...

    def list_assets(self, instance_id: str) -> list[VectorStoreInstanceAsset]: ...

    def add_asset(
        self, asset: VectorStoreInstanceAsset
    ) -> VectorStoreInstanceAsset: ...

    def remove_asset(self, instance_id: str, relation_id: str) -> None: ...
