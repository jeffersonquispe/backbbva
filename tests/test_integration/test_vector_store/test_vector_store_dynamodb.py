"""Docker-only integration tests against the real DynamoDB Local service."""
from __future__ import annotations

import os
import uuid

import pytest

if not os.getenv("DYNAMO_ENDPOINT"):
    pytest.skip("Requires DynamoDB Local; run through make test-integration-docker-vector-store", allow_module_level=True)

from src.application.ports.configuration_port import FlagType
from src.application.ports.embedding_port import (
    EmbeddingResult,
    EmbeddingUnitOfWork,
    EmbeddingUnitOfWorkFactory,
)
from src.application.ports.monitoring_port import MonitoringPort, MonitoringSpan
from src.application.ports.vector_store_instance_port import KnowledgeAssetType
from src.application.use_cases.flag_library.create_flag_library_entry import (
    CreateFlagLibraryEntryUseCase,
)
from src.application.use_cases.modus_operandi_library.create_modus_operandi_library_entry import (
    CreateModusOperandiLibraryEntryUseCase,
)
from src.application.use_cases.similar_case_library.create_similar_case_library_entry import (
    CreateSimilarCaseLibraryEntryUseCase,
)
from src.application.use_cases.taxonomy_library.create_taxonomy_library_entry import (
    CreateTaxonomyLibraryEntryUseCase,
)
from src.application.use_cases.vector_store_instances.create_vector_store_instance import (
    CreateVectorStoreInstanceUseCase,
)
from src.application.use_cases.vector_store_instances.knowledge_graph import (
    KnowledgeGraphService,
)
from src.infrastructure.persistence.database.dynamodb.manager import ensure_all_tables
from src.infrastructure.persistence.database.dynamodb.repositories.flag_library_repository import (
    DynamoFlagLibraryRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.modus_operandi_library_repository import (
    DynamoModusOperandiLibraryRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.similar_case_library_repository import (
    DynamoSimilarCaseLibraryRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.taxonomy_library_repository import (
    DynamoTaxonomyLibraryRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.vector_store_instance_repository import (
    DynamoVectorStoreInstanceRepository,
)

pytestmark = pytest.mark.docker_integration


class _ScriptedEmbeddingUnitOfWork(EmbeddingUnitOfWork):
    def embed(self, texts: list[str]) -> EmbeddingResult:
        return EmbeddingResult(vectors=[[0.1, 0.2, 0.3] for _ in texts], model="fake", dimensions=3)


class _ScriptedEmbeddingUnitOfWorkFactory(EmbeddingUnitOfWorkFactory):
    def create(self, *, model: str, monitoring: MonitoringPort, operation_name: str) -> EmbeddingUnitOfWork:
        return _ScriptedEmbeddingUnitOfWork()


class _NullSpan(MonitoringSpan):
    def write_input(self, data) -> None: pass
    def write_result(self, data) -> None: pass
    def write_inner_logs(self, entries) -> None: pass
    def write_operation_metas(self, metadata) -> None: pass
    def record_dependency(self, name, kind, metadata=None) -> None: pass
    def finish(self, error=None) -> None: pass


class _NullMonitoringPort(MonitoringPort):
    def start(self, operation_name, operation_type, metadata=None) -> MonitoringSpan:
        return _NullSpan()


def _embedding_kwargs() -> dict:
    return dict(
        embedding_unit_of_work_factory=_ScriptedEmbeddingUnitOfWorkFactory(),
        monitoring=_NullMonitoringPort(),
        embedding_model="fake-deployment",
    )


@pytest.fixture(scope="module", autouse=True)
def tables() -> None:
    ensure_all_tables()


def _graph():
    return KnowledgeGraphService(
        instances=DynamoVectorStoreInstanceRepository(),
        taxonomies=DynamoTaxonomyLibraryRepository(),
        modus_operandi=DynamoModusOperandiLibraryRepository(),
        flags=DynamoFlagLibraryRepository(),
        similar_cases=DynamoSimilarCaseLibraryRepository(),
    )


def _seed_tree():
    suffix = uuid.uuid4().hex
    taxonomies = DynamoTaxonomyLibraryRepository()
    modus = DynamoModusOperandiLibraryRepository()
    flags = DynamoFlagLibraryRepository()
    cases = DynamoSimilarCaseLibraryRepository()
    tax = CreateTaxonomyLibraryEntryUseCase(taxonomies, **_embedding_kwargs()).execute(f"T-{suffix[:8]}", f"Taxonomía {suffix}")
    mo = CreateModusOperandiLibraryEntryUseCase(modus, **_embedding_kwargs()).execute(f"MO {suffix}", "Narrativa de prueba", tax.id)
    case = CreateSimilarCaseLibraryEntryUseCase(cases, **_embedding_kwargs()).execute(f"Caso {suffix}", mo.id, tax.id)
    yellow = CreateFlagLibraryEntryUseCase(flags, **_embedding_kwargs()).execute(FlagType.YELLOW, f"Yellow {suffix}", modus_operandi_library_ids=[mo.id])
    red = CreateFlagLibraryEntryUseCase(flags, **_embedding_kwargs()).execute(FlagType.RED, f"Red {suffix}", modus_operandi_library_ids=[mo.id])
    return tax, mo, case, yellow, red


def test_dynamodb_persists_full_tree_and_idempotent_relations() -> None:
    tax, mo, case, yellow, red = _seed_tree()
    repository = DynamoVectorStoreInstanceRepository()
    instance = CreateVectorStoreInstanceUseCase(repository).execute(
        name=f"Integration {uuid.uuid4().hex}", description="DynamoDB local", created_by="integration-test", assets=[]
    )
    graph = _graph()

    first = graph.attach(instance.id, KnowledgeAssetType.TAXONOMY, tax.id)
    second = graph.attach(instance.id, KnowledgeAssetType.TAXONOMY, tax.id)
    persisted = repository.list_assets(instance.id)

    assert len(first) == 5
    assert second == []
    assert {(asset.asset_type, asset.asset_id) for asset in persisted} == {
        (KnowledgeAssetType.TAXONOMY, tax.id), (KnowledgeAssetType.MODUS_OPERANDI, mo.id),
        (KnowledgeAssetType.SIMILAR_CASE, case.id), (KnowledgeAssetType.YELLOW_FLAG, yellow.id),
        (KnowledgeAssetType.RED_FLAG, red.id),
    }


def test_dynamodb_propagates_new_descendant_and_removes_recursive_tree() -> None:
    tax, mo, _, _, _ = _seed_tree()
    repository = DynamoVectorStoreInstanceRepository()
    instance = CreateVectorStoreInstanceUseCase(repository).execute(
        name=f"Propagation {uuid.uuid4().hex}", description="DynamoDB local", created_by="integration-test", assets=[]
    )
    graph = _graph()
    graph.attach(instance.id, KnowledgeAssetType.TAXONOMY, tax.id)

    new_case = CreateSimilarCaseLibraryEntryUseCase(DynamoSimilarCaseLibraryRepository(), **_embedding_kwargs()).execute(
        f"Caso posterior {uuid.uuid4().hex}", mo.id, tax.id
    )
    assert graph.synchronize_new_asset(KnowledgeAssetType.SIMILAR_CASE, new_case.id) == [instance.id]
    assert any(asset.asset_id == new_case.id for asset in repository.list_assets(instance.id))

    assert graph.detach_tree_from_all_instances(KnowledgeAssetType.TAXONOMY, tax.id) == [instance.id]
    assert repository.list_assets(instance.id) == []
