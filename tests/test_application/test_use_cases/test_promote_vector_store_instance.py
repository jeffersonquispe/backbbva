from __future__ import annotations

import uuid
from datetime import UTC, datetime
from threading import Event, Thread

import pytest

from src.application.ports.embedding_port import (
    EmbeddingResult,
    EmbeddingUnitOfWork,
    EmbeddingUnitOfWorkFactory,
)
from src.application.ports.flag_library_port import FlagLibraryEntry
from src.application.ports.fraud_knowledge_port import (
    DocumentType,
    FraudKnowledgeDocument,
    ModusOperandiDocument,
)
from src.application.ports.modus_operandi_library_port import ModusOperandiLibraryEntry
from src.application.ports.monitoring_port import MonitoringPort, MonitoringSpan
from src.application.ports.similar_case_library_port import SimilarCaseLibraryEntry
from src.application.ports.taxonomy_library_port import TaxonomyLibraryEntry
from src.application.ports.vector_store_instance_port import (
    KnowledgeAssetType,
    VectorStoreInstance,
    VectorStoreInstanceAsset,
)
from src.application.use_cases.fraud_knowledge.ingest_flag import IngestFlagUseCase
from src.application.use_cases.fraud_knowledge.ingest_modus_operandi import (
    IngestModusOperandiUseCase,
)
from src.application.use_cases.fraud_knowledge.ingest_similar_case import (
    IngestSimilarCaseUseCase,
)
from src.application.use_cases.fraud_knowledge.ingest_taxonomia import (
    IngestTaxonomiaUseCase,
)
from src.application.use_cases.vector_store_instances.manage_vector_store_instance import (
    VectorStoreInstanceNotFoundError,
)
from src.application.use_cases.vector_store_instances.promote_vector_store_instance import (
    EmptyVectorStoreInstanceError,
    PromoteVectorStoreInstanceUseCase,
)
from src.domain.configurations.entities import (
    FlagType,
)


class InMemoryLibrary:
    def __init__(self, items: dict) -> None:
        self.items = items

    def get(self, entry_id):
        return self.items.get(entry_id)

    def list(self, *, active_only: bool = False):
        return list(self.items.values())


class InMemoryFraudKnowledgeRepository:
    def __init__(self) -> None:
        self._documents: dict[uuid.UUID, FraudKnowledgeDocument] = {}

    def create(self, document: FraudKnowledgeDocument) -> FraudKnowledgeDocument:
        self._documents[document.id] = document
        return document

    def get(self, document_id: uuid.UUID) -> FraudKnowledgeDocument | None:
        return self._documents.get(document_id)

    def update(self, document: FraudKnowledgeDocument) -> FraudKnowledgeDocument:
        self._documents[document.id] = document
        return document

    def delete(self, document_id: uuid.UUID) -> None:
        self._documents.pop(document_id, None)

    def list(
        self,
        document_type: DocumentType | None = None,
        *,
        vector_store_id: str | None = None,
        vector_store_version: int | None = None,
    ) -> list[FraudKnowledgeDocument]:
        results = list(self._documents.values())
        if document_type is not None:
            results = [d for d in results if d.type == document_type]
        if vector_store_id is not None:
            results = [d for d in results if d.vector_store_id == vector_store_id]
        if vector_store_version is not None:
            results = [
                d for d in results if d.vector_store_version == vector_store_version
            ]
        return results


class FailOnNthCreateRepository(InMemoryFraudKnowledgeRepository):
    def __init__(self) -> None:
        super().__init__()
        self._fail_on_create: int | None = None
        self._create_count = 0

    def create(self, document: FraudKnowledgeDocument) -> FraudKnowledgeDocument:
        self._create_count += 1
        if self._create_count == self._fail_on_create:
            raise RuntimeError("injected OpenSearch write failure")
        return super().create(document)


class PauseOnNthCreateRepository(InMemoryFraudKnowledgeRepository):
    def __init__(self, pause_on_create: int) -> None:
        super().__init__()
        self.pause_on_create = pause_on_create
        self.create_count = 0
        self.paused = Event()
        self.resume = Event()

    def create(self, document: FraudKnowledgeDocument) -> FraudKnowledgeDocument:
        self.create_count += 1
        if self.create_count == self.pause_on_create:
            self.paused.set()
            if not self.resume.wait(timeout=10):
                raise TimeoutError("promotion test was not resumed")
        return super().create(document)


class InMemoryVectorStoreInstanceRepository:
    def __init__(
        self, instance: VectorStoreInstance, assets: list[VectorStoreInstanceAsset]
    ) -> None:
        self._instance = instance
        self._assets = assets

    def create(self, instance, assets):
        raise NotImplementedError

    def list(self):
        return [self._instance]

    def get(self, instance_id: str) -> VectorStoreInstance | None:
        return self._instance if instance_id == self._instance.id else None

    def update(self, instance: VectorStoreInstance) -> VectorStoreInstance:
        self._instance = instance
        return instance

    def list_assets(self, instance_id: str) -> list[VectorStoreInstanceAsset]:
        return list(self._assets) if instance_id == self._instance.id else []

    def add_asset(self, asset):
        self._assets.append(asset)
        return asset

    def remove_asset(self, instance_id, relation_id) -> None:
        raise NotImplementedError


class CountingEmbeddingUnitOfWork(EmbeddingUnitOfWork):
    def __init__(self, counter: list[int]) -> None:
        self._counter = counter

    def embed(self, texts: list[str]) -> EmbeddingResult:
        self._counter[0] += 1
        return EmbeddingResult(
            vectors=[[0.9, 0.9, 0.9] for _ in texts], model="fake", dimensions=3
        )


class CountingEmbeddingUnitOfWorkFactory(EmbeddingUnitOfWorkFactory):
    def __init__(self) -> None:
        self.calls = [0]

    def create(
        self, *, model: str, monitoring: MonitoringPort, operation_name: str
    ) -> EmbeddingUnitOfWork:
        return CountingEmbeddingUnitOfWork(self.calls)


class NullSpan(MonitoringSpan):
    def write_input(self, data) -> None:
        pass

    def write_result(self, data) -> None:
        pass

    def write_inner_logs(self, entries) -> None:
        pass

    def write_operation_metas(self, metadata) -> None:
        pass

    def record_dependency(self, name, kind, metadata=None) -> None:
        pass

    def finish(self, error=None) -> None:
        pass


class NullMonitoringPort(MonitoringPort):
    def start(self, operation_name, operation_type, metadata=None) -> MonitoringSpan:
        return NullSpan()


def _instance(promoted_version: int | None = None) -> VectorStoreInstance:
    return VectorStoreInstance(
        id="vector-store-v1",
        version=1,
        name="Producción",
        description="",
        created_at=datetime.now(UTC),
        created_by="tester",
        promoted_version=promoted_version,
    )


def _full_tree_use_case(
    *,
    instance: VectorStoreInstance,
    assets: list[VectorStoreInstanceAsset],
    taxonomy: TaxonomyLibraryEntry,
    modus_operandi: ModusOperandiLibraryEntry,
    flag: FlagLibraryEntry,
    case: SimilarCaseLibraryEntry,
    embedding_factory: CountingEmbeddingUnitOfWorkFactory,
    fraud_repo: InMemoryFraudKnowledgeRepository | None = None,
) -> tuple[
    PromoteVectorStoreInstanceUseCase,
    InMemoryFraudKnowledgeRepository,
    InMemoryVectorStoreInstanceRepository,
]:
    fraud_repo = fraud_repo or InMemoryFraudKnowledgeRepository()
    instances = InMemoryVectorStoreInstanceRepository(instance, assets)
    kwargs = dict(
        repository=fraud_repo,
        embedding_unit_of_work_factory=embedding_factory,
        monitoring=NullMonitoringPort(),
        embedding_model="fake-deployment",
    )
    use_case = PromoteVectorStoreInstanceUseCase(
        instances=instances,
        taxonomies=InMemoryLibrary({taxonomy.id: taxonomy}),
        modus_operandi=InMemoryLibrary({modus_operandi.id: modus_operandi}),
        flags=InMemoryLibrary({flag.id: flag}),
        similar_cases=InMemoryLibrary({case.id: case}),
        fraud_knowledge_repository=fraud_repo,
        ingest_taxonomia=IngestTaxonomiaUseCase(**kwargs),
        ingest_modus_operandi=IngestModusOperandiUseCase(**kwargs),
        ingest_flag=IngestFlagUseCase(**kwargs),
        ingest_similar_case=IngestSimilarCaseUseCase(**kwargs),
    )
    return use_case, fraud_repo, instances


def _seed_full_tree(now):
    taxonomy = TaxonomyLibraryEntry(
        id="tax-1",
        code="PHISH",
        name="Phishing",
        description="desc",
        created_at=now,
        updated_at=now,
        embedding=[0.1, 0.1],
    )
    mo = ModusOperandiLibraryEntry(
        id="mo-1",
        title="Vishing",
        narrative="narrativa",
        taxonomy_library_id="tax-1",
        created_at=now,
        updated_at=now,
        embedding=[0.2, 0.2],
    )
    flag = FlagLibraryEntry(
        id="flag-1",
        flag_type=FlagType.RED,
        name="Alerta",
        description="desc",
        modus_operandi_library_ids=["mo-1"],
        created_at=now,
        updated_at=now,
        embedding=[0.3, 0.3],
    )
    case = SimilarCaseLibraryEntry(
        id="case-1",
        text="caso similar",
        modus_operandi_library_id="mo-1",
        taxonomy_library_id="tax-1",
        created_at=now,
        updated_at=now,
        embedding=[0.4, 0.4],
    )
    assets = [
        VectorStoreInstanceAsset(
            "vector-store-v1",
            KnowledgeAssetType.TAXONOMY,
            "tax-1",
            1,
            embedding=taxonomy.embedding,
        ),
        VectorStoreInstanceAsset(
            "vector-store-v1",
            KnowledgeAssetType.MODUS_OPERANDI,
            "mo-1",
            1,
            embedding=mo.embedding,
        ),
        VectorStoreInstanceAsset(
            "vector-store-v1",
            KnowledgeAssetType.RED_FLAG,
            "flag-1",
            1,
            embedding=flag.embedding,
        ),
        VectorStoreInstanceAsset(
            "vector-store-v1",
            KnowledgeAssetType.SIMILAR_CASE,
            "case-1",
            1,
            embedding=case.embedding,
        ),
    ]
    return taxonomy, mo, flag, case, assets


def test_promote_loads_full_tree_and_recycles_every_embedding() -> None:
    now = datetime.now(UTC)
    taxonomy, mo, flag, case, assets = _seed_full_tree(now)
    embedding_factory = CountingEmbeddingUnitOfWorkFactory()
    use_case, fraud_repo, instances = _full_tree_use_case(
        instance=_instance(),
        assets=assets,
        taxonomy=taxonomy,
        modus_operandi=mo,
        flag=flag,
        case=case,
        embedding_factory=embedding_factory,
    )

    promoted = use_case.execute("vector-store-v1", actor="manager")

    assert promoted.promoted_version == 1
    assert promoted.promoted_by == "manager"
    assert promoted.promoted_at is not None
    # Every asset already had a cached embedding - promotion must never call
    # the embedding API.
    assert embedding_factory.calls[0] == 0

    documents = fraud_repo.list(
        vector_store_id="vector-store-v1", vector_store_version=1
    )
    assert len(documents) == 4
    by_type = {doc.type: doc for doc in documents}
    mo_doc = by_type[DocumentType.MODUS_OPERANDI]
    assert isinstance(mo_doc, ModusOperandiDocument)
    assert mo_doc.taxonomia_id == by_type[DocumentType.TAXONOMIA].id
    assert mo_doc.flags == [by_type[DocumentType.RED_FLAG].id]
    assert mo_doc.similar_cases == [by_type[DocumentType.SIMILAR_CASE].id]
    # Stable join key back to the Library entry - see
    # ModusOperandiDocument.library_id's docstring.
    assert mo_doc.library_id == "mo-1"


def test_repromoting_deletes_previous_generation_after_loading_the_new_one() -> None:
    now = datetime.now(UTC)
    taxonomy, mo, flag, case, assets = _seed_full_tree(now)
    embedding_factory = CountingEmbeddingUnitOfWorkFactory()
    use_case, fraud_repo, instances = _full_tree_use_case(
        instance=_instance(),
        assets=assets,
        taxonomy=taxonomy,
        modus_operandi=mo,
        flag=flag,
        case=case,
        embedding_factory=embedding_factory,
    )
    use_case.execute("vector-store-v1", actor="manager")

    promoted_again = use_case.execute("vector-store-v1", actor="manager")

    assert promoted_again.promoted_version == 2
    assert (
        fraud_repo.list(vector_store_id="vector-store-v1", vector_store_version=1) == []
    )
    assert (
        len(fraud_repo.list(vector_store_id="vector-store-v1", vector_store_version=2))
        == 4
    )


def test_repromotion_write_failure_keeps_previous_generation_and_rolls_back_partial_new_generation() -> None:
    now = datetime.now(UTC)
    taxonomy, mo, flag, case, assets = _seed_full_tree(now)
    embedding_factory = CountingEmbeddingUnitOfWorkFactory()
    fraud_repo = FailOnNthCreateRepository()
    use_case, fraud_repo, instances = _full_tree_use_case(
        instance=_instance(),
        assets=assets,
        taxonomy=taxonomy,
        modus_operandi=mo,
        flag=flag,
        case=case,
        embedding_factory=embedding_factory,
        fraud_repo=fraud_repo,
    )
    use_case.execute("vector-store-v1", actor="manager")
    previous = fraud_repo.list(
        vector_store_id="vector-store-v1", vector_store_version=1
    )

    # Fail on the third write of the second promotion. The first two new
    # documents have already been persisted at this point.
    fraud_repo._fail_on_create = fraud_repo._create_count + 3
    with pytest.raises(RuntimeError, match="injected OpenSearch write failure"):
        use_case.execute("vector-store-v1", actor="manager")

    assert instances.get("vector-store-v1").promoted_version == 1
    assert fraud_repo.list(
        vector_store_id="vector-store-v1", vector_store_version=1
    ) == previous
    assert fraud_repo.list(
        vector_store_id="vector-store-v1", vector_store_version=2
    ) == []


def test_previous_generation_remains_available_while_next_generation_is_loading() -> None:
    now = datetime.now(UTC)
    taxonomy, mo, flag, case, assets = _seed_full_tree(now)
    embedding_factory = CountingEmbeddingUnitOfWorkFactory()
    fraud_repo = PauseOnNthCreateRepository(pause_on_create=5)
    use_case, fraud_repo, instances = _full_tree_use_case(
        instance=_instance(),
        assets=assets,
        taxonomy=taxonomy,
        modus_operandi=mo,
        flag=flag,
        case=case,
        embedding_factory=embedding_factory,
        fraud_repo=fraud_repo,
    )
    use_case.execute("vector-store-v1", actor="manager")
    previous = fraud_repo.list(
        vector_store_id="vector-store-v1", vector_store_version=1
    )
    error: list[Exception] = []

    def repromote() -> None:
        try:
            use_case.execute("vector-store-v1", actor="manager")
        except Exception as exc:  # noqa: BLE001 - forward worker-thread failures
            error.append(exc)

    thread = Thread(target=repromote)
    thread.start()
    assert fraud_repo.paused.wait(timeout=10)
    assert instances.get("vector-store-v1").promoted_version == 1
    assert fraud_repo.list(
        vector_store_id="vector-store-v1", vector_store_version=1
    ) == previous
    assert fraud_repo.list(
        vector_store_id="vector-store-v1", vector_store_version=2
    ) == []

    fraud_repo.resume.set()
    thread.join(timeout=10)
    assert not thread.is_alive()
    assert error == []
    assert instances.get("vector-store-v1").promoted_version == 2


def test_promote_unknown_instance_raises() -> None:
    now = datetime.now(UTC)
    taxonomy, mo, flag, case, assets = _seed_full_tree(now)
    embedding_factory = CountingEmbeddingUnitOfWorkFactory()
    use_case, _, _ = _full_tree_use_case(
        instance=_instance(),
        assets=assets,
        taxonomy=taxonomy,
        modus_operandi=mo,
        flag=flag,
        case=case,
        embedding_factory=embedding_factory,
    )

    with pytest.raises(VectorStoreInstanceNotFoundError):
        use_case.execute("missing-instance", actor="manager")


def test_promote_empty_instance_raises() -> None:
    now = datetime.now(UTC)
    taxonomy, mo, flag, case, _ = _seed_full_tree(now)
    embedding_factory = CountingEmbeddingUnitOfWorkFactory()
    use_case, _, _ = _full_tree_use_case(
        instance=_instance(),
        assets=[],
        taxonomy=taxonomy,
        modus_operandi=mo,
        flag=flag,
        case=case,
        embedding_factory=embedding_factory,
    )

    with pytest.raises(EmptyVectorStoreInstanceError):
        use_case.execute("vector-store-v1", actor="manager")


def test_promote_modus_operandi_without_its_taxonomy_raises() -> None:
    now = datetime.now(UTC)
    taxonomy, mo, flag, case, _ = _seed_full_tree(now)
    assets = [
        VectorStoreInstanceAsset(
            "vector-store-v1",
            KnowledgeAssetType.MODUS_OPERANDI,
            "mo-1",
            1,
            embedding=mo.embedding,
        )
    ]
    embedding_factory = CountingEmbeddingUnitOfWorkFactory()
    use_case, _, _ = _full_tree_use_case(
        instance=_instance(),
        assets=assets,
        taxonomy=taxonomy,
        modus_operandi=mo,
        flag=flag,
        case=case,
        embedding_factory=embedding_factory,
    )

    with pytest.raises(ValueError, match="taxonomy"):
        use_case.execute("vector-store-v1", actor="manager")


def test_promote_flag_without_its_modus_operandi_drops_the_reference() -> None:
    now = datetime.now(UTC)
    taxonomy, mo, flag, case, _ = _seed_full_tree(now)
    assets = [
        VectorStoreInstanceAsset(
            "vector-store-v1",
            KnowledgeAssetType.RED_FLAG,
            "flag-1",
            1,
            embedding=flag.embedding,
        )
    ]
    embedding_factory = CountingEmbeddingUnitOfWorkFactory()
    use_case, fraud_repo, _ = _full_tree_use_case(
        instance=_instance(),
        assets=assets,
        taxonomy=taxonomy,
        modus_operandi=mo,
        flag=flag,
        case=case,
        embedding_factory=embedding_factory,
    )

    use_case.execute("vector-store-v1", actor="manager")

    [flag_doc] = fraud_repo.list(
        vector_store_id="vector-store-v1", vector_store_version=1
    )
    assert flag_doc.modus_operandi_ids == []


def test_promote_similar_case_without_its_modus_operandi_raises() -> None:
    now = datetime.now(UTC)
    taxonomy, mo, flag, case, _ = _seed_full_tree(now)
    assets = [
        VectorStoreInstanceAsset(
            "vector-store-v1",
            KnowledgeAssetType.TAXONOMY,
            "tax-1",
            1,
            embedding=taxonomy.embedding,
        ),
        VectorStoreInstanceAsset(
            "vector-store-v1",
            KnowledgeAssetType.SIMILAR_CASE,
            "case-1",
            1,
            embedding=case.embedding,
        ),
    ]
    embedding_factory = CountingEmbeddingUnitOfWorkFactory()
    use_case, _, _ = _full_tree_use_case(
        instance=_instance(),
        assets=assets,
        taxonomy=taxonomy,
        modus_operandi=mo,
        flag=flag,
        case=case,
        embedding_factory=embedding_factory,
    )

    with pytest.raises(ValueError, match="modus operandi"):
        use_case.execute("vector-store-v1", actor="manager")


def test_promote_falls_back_to_embedding_when_asset_relation_lacks_a_cached_one() -> (
    None
):
    now = datetime.now(UTC)
    taxonomy, mo, flag, case, _ = _seed_full_tree(now)
    # Relation row has no embedding, but the Library entry does - Library
    # entry embedding is the fallback, still no re-embedding needed.
    assets = [
        VectorStoreInstanceAsset(
            "vector-store-v1", KnowledgeAssetType.TAXONOMY, "tax-1", 1, embedding=None
        )
    ]
    embedding_factory = CountingEmbeddingUnitOfWorkFactory()
    use_case, fraud_repo, _ = _full_tree_use_case(
        instance=_instance(),
        assets=assets,
        taxonomy=taxonomy,
        modus_operandi=mo,
        flag=flag,
        case=case,
        embedding_factory=embedding_factory,
    )

    use_case.execute("vector-store-v1", actor="manager")

    assert embedding_factory.calls[0] == 0
    [doc] = fraud_repo.list(vector_store_id="vector-store-v1", vector_store_version=1)
    assert doc.text_embedded == taxonomy.embedding
