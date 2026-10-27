from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from hashlib import sha256
from uuid import UUID

from src.application.errors import ConflictError, NotFoundError, ValidationError
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
from src.application.ports.vector_store_generation_port import (
    VectorStoreGeneration,
    VectorStoreGenerationRepository,
    VectorStoreGenerationStatus,
    VectorStoreManifestItem,
)
from src.application.ports.vector_store_instance_port import (
    KnowledgeAssetType,
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
from src.domain.configurations.entities import FlagType


class EmptyVectorStoreInstanceError(ValidationError):
    pass


class VectorStoreBuildInProgressError(ConflictError):
    pass


@dataclass(frozen=True)
class BuildVectorStoreGenerationOutput:
    generation: VectorStoreGeneration
    # False when an existing READY generation already holds this exact
    # content and was returned instead of loading a duplicate.
    built: bool


@dataclass(frozen=True)
class _PlannedDocument:
    asset_type: KnowledgeAssetType
    asset_id: str
    asset_version: int
    text: str
    embedding: list[float] | None
    taxonomy_name: str = ""
    # Library ids of the documents this one links to; translated into the
    # new generation's OpenSearch ids at ingest time.
    taxonomy_library_id: str | None = None
    modus_operandi_library_ids: tuple[str, ...] = field(default_factory=tuple)

    def fingerprint_payload(self) -> dict[str, object]:
        return {
            "asset_type": self.asset_type.value,
            "asset_id": self.asset_id,
            "asset_version": self.asset_version,
            "text": self.text,
            "taxonomy_name": self.taxonomy_name,
            "embedding_sha256": (
                sha256(json.dumps(self.embedding).encode()).hexdigest()
                if self.embedding is not None
                else None
            ),
            "taxonomy_library_id": self.taxonomy_library_id,
            "modus_operandi_library_ids": list(self.modus_operandi_library_ids),
        }


_INGEST_ORDER = (
    KnowledgeAssetType.TAXONOMY,
    KnowledgeAssetType.MODUS_OPERANDI,
    KnowledgeAssetType.RED_FLAG,
    KnowledgeAssetType.YELLOW_FLAG,
    KnowledgeAssetType.SIMILAR_CASE,
)


class BuildVectorStoreGenerationUseCase:
    """Loads an instance's current manifest into OpenSearch as a new,
    immutable generation.

    Building publishes nothing: production searches the generation its
    active configuration pins, which only changes through an approved
    deploy request. The previous generations are left untouched - the
    retention job (CleanupVectorStoreGenerationsUseCase) retires the ones no
    configuration, test or release still needs.

    The manifest is resolved into the exact documents to ingest first. When
    a READY generation already holds the same content (same fingerprint),
    it is returned instead of loading a duplicate, so tests and
    configuration saves can call this freely. Embeddings are never
    recomputed when the Library entry already caches one.
    """

    def __init__(
        self,
        instances: VectorStoreInstanceRepository,
        generations: VectorStoreGenerationRepository,
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
        self._generations = generations
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

    def execute(
        self, instance_id: str, *, actor: str
    ) -> BuildVectorStoreGenerationOutput:
        if self._instances.get(instance_id) is None:
            raise VectorStoreInstanceNotFoundError(
                f"Vector store instance not found: {instance_id}"
            )
        planned = self.plan(instance_id)
        fingerprint = _fingerprint(planned)
        existing = self._generations.list(instance_id)
        for generation in reversed(existing):
            if (
                generation.status == VectorStoreGenerationStatus.READY
                and generation.fingerprint == fingerprint
            ):
                return BuildVectorStoreGenerationOutput(generation, built=False)
        if any(
            item.status == VectorStoreGenerationStatus.BUILDING for item in existing
        ):
            raise VectorStoreBuildInProgressError(
                f"Vector store instance {instance_id} is already building a generation"
            )

        number = max((item.generation for item in existing), default=0) + 1
        record = self._generations.create(
            VectorStoreGeneration(
                instance_id=instance_id,
                generation=number,
                status=VectorStoreGenerationStatus.BUILDING,
                built_by=actor,
                created_at=self._clock.now(),
                fingerprint=fingerprint,
                manifest=tuple(
                    VectorStoreManifestItem(
                        asset_type=item.asset_type.value,
                        asset_id=item.asset_id,
                        asset_version=item.asset_version,
                    )
                    for item in planned
                ),
            )
        )
        try:
            count = self._ingest(instance_id, number, planned)
        except Exception as error:
            # A failed build never becomes searchable: drop what it wrote.
            self._fraud_knowledge_repository.delete_generation(instance_id, number)
            self._generations.update(
                replace(
                    record,
                    status=VectorStoreGenerationStatus.FAILED,
                    error=type(error).__name__,
                )
            )
            raise
        ready = self._generations.update(
            replace(
                record,
                status=VectorStoreGenerationStatus.READY,
                document_count=count,
                ready_at=self._clock.now(),
            )
        )
        return BuildVectorStoreGenerationOutput(ready, built=True)

    def plan(self, instance_id: str) -> list[_PlannedDocument]:
        """The documents a build of the current manifest would load, in
        ingest order. Raises on a dangling or incomplete manifest."""
        assets = self._instances.list_assets(instance_id)
        if not assets:
            raise EmptyVectorStoreInstanceError(
                f"Vector store instance {instance_id} has no assets to build"
            )
        by_type: dict[KnowledgeAssetType, list] = {kind: [] for kind in _INGEST_ORDER}
        for asset in sorted(assets, key=lambda item: (item.asset_type, item.asset_id)):
            by_type[asset.asset_type].append(asset)

        planned: list[_PlannedDocument] = []
        taxonomy_ids: set[str] = set()
        for asset in by_type[KnowledgeAssetType.TAXONOMY]:
            tax_entry = self._taxonomies.get(asset.asset_id)
            if tax_entry is None:
                raise NotFoundError(
                    f"taxonomy library tax_entry {asset.asset_id} no longer exists"
                )
            taxonomy_ids.add(tax_entry.id)
            planned.append(
                _PlannedDocument(
                    asset_type=asset.asset_type,
                    asset_id=asset.asset_id,
                    asset_version=asset.asset_version,
                    text=taxonomia_embedding_text(
                        name=tax_entry.name,
                        description=tax_entry.description,
                        examples=tax_entry.examples,
                    ),
                    embedding=tax_entry.embedding,
                )
            )

        modus_operandi_ids: set[str] = set()
        for asset in by_type[KnowledgeAssetType.MODUS_OPERANDI]:
            mo_entry = self._modus_operandi.get(asset.asset_id)
            if mo_entry is None:
                raise NotFoundError(
                    f"modus operandi library mo_entry {asset.asset_id} no longer exists"
                )
            if mo_entry.taxonomy_library_id not in taxonomy_ids:
                raise ValidationError(
                    f"modus operandi {mo_entry.id!r}'s taxonomy {mo_entry.taxonomy_library_id!r} "
                    "is not included in this vector store instance"
                )
            taxonomy_entry = self._taxonomies.get(mo_entry.taxonomy_library_id)
            modus_operandi_ids.add(mo_entry.id)
            planned.append(
                _PlannedDocument(
                    asset_type=asset.asset_type,
                    asset_id=asset.asset_id,
                    asset_version=asset.asset_version,
                    text=modus_operandi_embedding_text(
                        title=mo_entry.title, narrative=mo_entry.narrative
                    ),
                    embedding=mo_entry.embedding,
                    taxonomy_name=taxonomy_entry.name if taxonomy_entry else "",
                    taxonomy_library_id=mo_entry.taxonomy_library_id,
                )
            )

        for asset in (
            by_type[KnowledgeAssetType.RED_FLAG] + by_type[KnowledgeAssetType.YELLOW_FLAG]
        ):
            flag_entry = self._flags.get(asset.asset_id)
            if flag_entry is None:
                raise NotFoundError(
                    f"flag library flag_entry {asset.asset_id} no longer exists"
                )
            # A flag can be attached standalone, without its parent modus
            # operandi(s) - drop references to whichever parents aren't
            # part of this vector store rather than failing the build.
            planned.append(
                _PlannedDocument(
                    asset_type=(
                        KnowledgeAssetType.RED_FLAG
                        if flag_entry.flag_type == FlagType.RED
                        else KnowledgeAssetType.YELLOW_FLAG
                    ),
                    asset_id=asset.asset_id,
                    asset_version=asset.asset_version,
                    text=flag_embedding_text(
                        name=flag_entry.name, description=flag_entry.description
                    ),
                    embedding=flag_entry.embedding,
                    modus_operandi_library_ids=tuple(
                        mid
                        for mid in flag_entry.modus_operandi_library_ids
                        if mid in modus_operandi_ids
                    ),
                )
            )

        for asset in by_type[KnowledgeAssetType.SIMILAR_CASE]:
            case_entry = self._similar_cases.get(asset.asset_id)
            if case_entry is None:
                raise NotFoundError(
                    f"similar case library case_entry {asset.asset_id} no longer exists"
                )
            if (
                case_entry.modus_operandi_library_id not in modus_operandi_ids
                or case_entry.taxonomy_library_id not in taxonomy_ids
            ):
                raise ValidationError(
                    f"similar case {case_entry.id!r}'s modus operandi {case_entry.modus_operandi_library_id!r} "
                    "and/or taxonomy are not included in this vector store instance"
                )
            planned.append(
                _PlannedDocument(
                    asset_type=asset.asset_type,
                    asset_id=asset.asset_id,
                    asset_version=asset.asset_version,
                    text=case_entry.text,
                    embedding=case_entry.embedding,
                    taxonomy_library_id=case_entry.taxonomy_library_id,
                    modus_operandi_library_ids=(case_entry.modus_operandi_library_id,),
                )
            )
        return planned

    def fingerprint(self, instance_id: str) -> str:
        return _fingerprint(self.plan(instance_id))

    def _ingest(
        self, instance_id: str, number: int, planned: list[_PlannedDocument]
    ) -> int:
        taxonomy_os_id: dict[str, UUID] = {}
        modus_operandi_os_id: dict[str, UUID] = {}
        count = 0
        for item in planned:
            if item.asset_type == KnowledgeAssetType.TAXONOMY:
                created = self._ingest_taxonomia.execute(
                    IngestTaxonomiaInput(
                        text=item.text,
                        vector_store_id=instance_id,
                        vector_store_version=number,
                        text_embedded=item.embedding,
                    )
                )
                taxonomy_os_id[item.asset_id] = created.id
            elif item.asset_type == KnowledgeAssetType.MODUS_OPERANDI:
                created_mo = self._ingest_modus_operandi.execute(
                    IngestModusOperandiInput(
                        text=item.text,
                        vector_store_id=instance_id,
                        vector_store_version=number,
                        taxonomia_id=taxonomy_os_id[item.taxonomy_library_id or ""],
                        taxonomia=item.taxonomy_name,
                        library_id=item.asset_id,
                        text_embedded=item.embedding,
                    )
                )
                modus_operandi_os_id[item.asset_id] = created_mo.id
            elif item.asset_type in (
                KnowledgeAssetType.RED_FLAG,
                KnowledgeAssetType.YELLOW_FLAG,
            ):
                self._ingest_flag.execute(
                    IngestFlagInput(
                        text=item.text,
                        flag_type=DocumentType.RED_FLAG
                        if item.asset_type == KnowledgeAssetType.RED_FLAG
                        else DocumentType.YELLOW_FLAG,
                        vector_store_id=instance_id,
                        vector_store_version=number,
                        modus_operandi_ids=[
                            modus_operandi_os_id[mid]
                            for mid in item.modus_operandi_library_ids
                        ],
                        text_embedded=item.embedding,
                    )
                )
            else:
                self._ingest_similar_case.execute(
                    IngestSimilarCaseInput(
                        text=item.text,
                        vector_store_id=instance_id,
                        vector_store_version=number,
                        modus_operandi_id=modus_operandi_os_id[
                            item.modus_operandi_library_ids[0]
                        ],
                        taxonomia_id=taxonomy_os_id[item.taxonomy_library_id or ""],
                        text_embedded=item.embedding,
                    )
                )
            count += 1
        return count


def _fingerprint(planned: list[_PlannedDocument]) -> str:
    payload = json.dumps(
        [item.fingerprint_payload() for item in planned],
        sort_keys=True,
        ensure_ascii=False,
    )
    return sha256(payload.encode()).hexdigest()
