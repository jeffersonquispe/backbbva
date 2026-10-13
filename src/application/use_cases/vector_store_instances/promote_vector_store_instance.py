from __future__ import annotations

from dataclasses import replace
from uuid import UUID

from src.application.errors import NotFoundError, ValidationError
from src.application.ports.clock_port import Clock
from src.application.ports.flag_library_port import FlagLibraryRepository
from src.application.ports.fraud_knowledge_port import DocumentType
from src.application.ports.fraud_knowledge_repository_port import (
    FraudKnowledgeRepository,
)
from src.application.ports.modus_operandi_library_port import (
    ModusOperandiLibraryRepository,
)
from src.application.ports.similar_case_library_port import SimilarCaseLibraryRepository
from src.application.ports.taxonomy_library_port import TaxonomyLibraryRepository
from src.application.ports.vector_store_instance_port import (
    KnowledgeAssetType,
    VectorStoreInstance,
    VectorStoreInstanceRepository,
)
from src.application.runtime_defaults import resolve_clock
from src.application.use_cases.flag_library.create_flag_library_entry import (
    embedding_text as flag_embedding_text,
)
from src.application.use_cases.fraud_knowledge.ingest_flag import (
    IngestFlagInput,
    IngestFlagUseCase,
)
from src.application.use_cases.fraud_knowledge.ingest_modus_operandi import (
    IngestModusOperandiInput,
    IngestModusOperandiUseCase,
)
from src.application.use_cases.fraud_knowledge.ingest_similar_case import (
    IngestSimilarCaseInput,
    IngestSimilarCaseUseCase,
)
from src.application.use_cases.fraud_knowledge.ingest_taxonomia import (
    IngestTaxonomiaInput,
    IngestTaxonomiaUseCase,
)
from src.application.use_cases.modus_operandi_library.create_modus_operandi_library_entry import (
    embedding_text as modus_operandi_embedding_text,
)
from src.application.use_cases.taxonomy_library.create_taxonomy_library_entry import (
    embedding_text as taxonomia_embedding_text,
)
from src.application.use_cases.vector_store_instances.manage_vector_store_instance import (
    VectorStoreInstanceNotFoundError,
)
from src.domain.configurations.entities import (
    FlagType,
)


class EmptyVectorStoreInstanceError(ValidationError):
    pass


class PromoteVectorStoreInstanceUseCase:
    """Builds this instance's production generation in OpenSearch from its
    DynamoDB asset manifest, then retires the previous one.

    Only "carga" (load) and "eliminación" (delete) happen against OpenSearch
    - never an in-place edit. Re-promoting a changed instance therefore
    means a full rebuild: load the new generation completely first (so a
    concurrent search never sees a gap), then delete the old one. Embeddings
    are never recomputed here - every Library entry already carries its own
    cached embedding (computed on its own create/update), recycled via
    Ingest*Input.text_embedded.
    """

    def __init__(
        self,
        instances: VectorStoreInstanceRepository,
        taxonomies: TaxonomyLibraryRepository,
        modus_operandi: ModusOperandiLibraryRepository,
        flags: FlagLibraryRepository,
        similar_cases: SimilarCaseLibraryRepository,
        fraud_knowledge_repository: FraudKnowledgeRepository,
        ingest_taxonomia: IngestTaxonomiaUseCase,
        ingest_modus_operandi: IngestModusOperandiUseCase,
        ingest_flag: IngestFlagUseCase,
        ingest_similar_case: IngestSimilarCaseUseCase,
        clock: Clock | None = None,
    ) -> None:
        self._instances = instances
        self._taxonomies = taxonomies
        self._modus_operandi = modus_operandi
        self._flags = flags
        self._similar_cases = similar_cases
        self._fraud_knowledge_repository = fraud_knowledge_repository
        self._ingest_taxonomia = ingest_taxonomia
        self._ingest_modus_operandi = ingest_modus_operandi
        self._ingest_flag = ingest_flag
        self._ingest_similar_case = ingest_similar_case
        self._clock = resolve_clock(clock)

    def execute(self, instance_id: str, *, actor: str) -> VectorStoreInstance:
        instance = self._instances.get(instance_id)
        if instance is None:
            raise VectorStoreInstanceNotFoundError(
                f"Vector store instance not found: {instance_id}"
            )

        assets = self._instances.list_assets(instance_id)
        if not assets:
            raise EmptyVectorStoreInstanceError(
                f"Vector store instance {instance_id} has no assets to promote"
            )

        new_version = (instance.promoted_version or 0) + 1
        previous_version = instance.promoted_version

        taxonomia_os_id: dict[str, UUID] = {}
        for asset in assets:
            if asset.asset_type != KnowledgeAssetType.TAXONOMY:
                continue
            entry = self._taxonomies.get(asset.asset_id)
            if entry is None:
                raise NotFoundError(
                    f"taxonomy library entry {asset.asset_id} no longer exists"
                )
            created = self._ingest_taxonomia.execute(
                IngestTaxonomiaInput(
                    text=taxonomia_embedding_text(
                        name=entry.name,
                        description=entry.description,
                        examples=entry.examples,
                    ),
                    vector_store_id=instance_id,
                    vector_store_version=new_version,
                    text_embedded=asset.embedding or entry.embedding,
                )
            )
            taxonomia_os_id[entry.id] = created.id

        modus_operandi_os_id: dict[str, UUID] = {}
        for asset in assets:
            if asset.asset_type != KnowledgeAssetType.MODUS_OPERANDI:
                continue
            entry = self._modus_operandi.get(asset.asset_id)
            if entry is None:
                raise NotFoundError(
                    f"modus operandi library entry {asset.asset_id} no longer exists"
                )
            taxonomia_id = taxonomia_os_id.get(entry.taxonomy_library_id)
            if taxonomia_id is None:
                raise ValidationError(
                    f"modus operandi {entry.id!r}'s taxonomy {entry.taxonomy_library_id!r} "
                    "is not included in this vector store instance"
                )
            taxonomy_entry = self._taxonomies.get(entry.taxonomy_library_id)
            created = self._ingest_modus_operandi.execute(
                IngestModusOperandiInput(
                    text=modus_operandi_embedding_text(
                        title=entry.title, narrative=entry.narrative
                    ),
                    vector_store_id=instance_id,
                    vector_store_version=new_version,
                    taxonomia_id=taxonomia_id,
                    taxonomia=taxonomy_entry.name if taxonomy_entry else "",
                    library_id=entry.id,
                    text_embedded=asset.embedding or entry.embedding,
                )
            )
            modus_operandi_os_id[entry.id] = created.id

        for asset in assets:
            if asset.asset_type not in (
                KnowledgeAssetType.RED_FLAG,
                KnowledgeAssetType.YELLOW_FLAG,
            ):
                continue
            entry = self._flags.get(asset.asset_id)
            if entry is None:
                raise NotFoundError(
                    f"flag library entry {asset.asset_id} no longer exists"
                )
            # A flag can be attached standalone, without its parent modus
            # operandi(s) - drop references to whichever parents aren't
            # part of this vector store rather than failing the promotion.
            resolved_mo_ids = [
                modus_operandi_os_id[mid]
                for mid in entry.modus_operandi_library_ids
                if mid in modus_operandi_os_id
            ]
            self._ingest_flag.execute(
                IngestFlagInput(
                    text=flag_embedding_text(
                        name=entry.name, description=entry.description
                    ),
                    flag_type=DocumentType.RED_FLAG
                    if entry.flag_type == FlagType.RED
                    else DocumentType.YELLOW_FLAG,
                    vector_store_id=instance_id,
                    vector_store_version=new_version,
                    modus_operandi_ids=resolved_mo_ids,
                    text_embedded=asset.embedding or entry.embedding,
                )
            )

        for asset in assets:
            if asset.asset_type != KnowledgeAssetType.SIMILAR_CASE:
                continue
            entry = self._similar_cases.get(asset.asset_id)
            if entry is None:
                raise NotFoundError(
                    f"similar case library entry {asset.asset_id} no longer exists"
                )
            modus_operandi_id = modus_operandi_os_id.get(
                entry.modus_operandi_library_id
            )
            taxonomia_id = taxonomia_os_id.get(entry.taxonomy_library_id)
            if modus_operandi_id is None or taxonomia_id is None:
                raise ValidationError(
                    f"similar case {entry.id!r}'s modus operandi {entry.modus_operandi_library_id!r} "
                    "and/or taxonomy are not included in this vector store instance"
                )
            self._ingest_similar_case.execute(
                IngestSimilarCaseInput(
                    text=entry.text,
                    vector_store_id=instance_id,
                    vector_store_version=new_version,
                    modus_operandi_id=modus_operandi_id,
                    taxonomia_id=taxonomia_id,
                    text_embedded=asset.embedding or entry.embedding,
                )
            )

        # New generation is fully loaded and searchable - only now retire
        # the previous one, so a concurrent search never sees a gap.
        if previous_version is not None:
            for document in self._fraud_knowledge_repository.list(
                vector_store_id=instance_id, vector_store_version=previous_version
            ):
                self._fraud_knowledge_repository.delete(document.id)

        promoted = replace(
            instance,
            promoted_version=new_version,
            promoted_at=self._clock.now(),
            promoted_by=actor,
        )
        return self._instances.update(promoted)
