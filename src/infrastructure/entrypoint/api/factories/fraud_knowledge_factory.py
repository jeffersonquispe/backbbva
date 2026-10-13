from __future__ import annotations

from functools import lru_cache

from src.application.ports.embedding_port import EmbeddingUnitOfWorkFactory
from src.application.ports.fraud_knowledge_port import FraudKnowledgeSearchPort
from src.application.ports.fraud_knowledge_relations_port import (
    FraudKnowledgeRelationsPort,
)
from src.application.ports.fraud_knowledge_repository_port import (
    FraudKnowledgeRepository,
)
from src.application.ports.monitoring_port import MonitoringPort
from src.application.use_cases.fraud_knowledge.delete_flag import DeleteFlagUseCase
from src.application.use_cases.fraud_knowledge.delete_modus_operandi import (
    DeleteModusOperandiUseCase,
)
from src.application.use_cases.fraud_knowledge.delete_similar_case import (
    DeleteSimilarCaseUseCase,
)
from src.application.use_cases.fraud_knowledge.delete_taxonomia import (
    DeleteTaxonomiaUseCase,
)
from src.application.use_cases.fraud_knowledge.get_related_fraud_knowledge import (
    GetRelatedFraudKnowledgeUseCase,
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
from src.application.use_cases.fraud_knowledge.list_fraud_knowledge_documents import (
    ListFraudKnowledgeDocumentsUseCase,
)
from src.application.use_cases.fraud_knowledge.search_fraud_knowledge import (
    SearchFraudKnowledgeUseCase,
)
from src.infrastructure.core.config import genai_config
from src.infrastructure.core.runtime.uuid_generator import get_id_generator
from src.infrastructure.embedding.langchain import get_embedding_unit_of_work_factory
from src.infrastructure.monitoring.opentelemetry import get_monitoring
from src.infrastructure.persistence.vector_store.opensearch.client import (
    get_opensearch_client,
)
from src.infrastructure.persistence.vector_store.opensearch.relations import (
    OpenSearchFraudKnowledgeRelationsAdapter,
)
from src.infrastructure.persistence.vector_store.opensearch.repository import (
    OpenSearchFraudKnowledgeRepository,
)
from src.infrastructure.persistence.vector_store.opensearch.search import (
    OpenSearchFraudKnowledgeSearchAdapter,
)


@lru_cache
def get_fraud_knowledge_repository() -> FraudKnowledgeRepository:
    return OpenSearchFraudKnowledgeRepository(get_opensearch_client())


@lru_cache
def get_fraud_knowledge_search_port() -> FraudKnowledgeSearchPort:
    return OpenSearchFraudKnowledgeSearchAdapter(
        client=get_opensearch_client(),
        embedding_unit_of_work_factory=get_embedding_unit_of_work_factory(),
        monitoring=get_monitoring(),
        embedding_model=genai_config.EMBEDDING_MODEL,
    )


@lru_cache
def get_fraud_knowledge_relations_port() -> FraudKnowledgeRelationsPort:
    return OpenSearchFraudKnowledgeRelationsAdapter(get_fraud_knowledge_repository())


def _embedding_deps() -> tuple[EmbeddingUnitOfWorkFactory, MonitoringPort, str]:
    return (
        get_embedding_unit_of_work_factory(),
        get_monitoring(),
        genai_config.EMBEDDING_MODEL,
    )


def get_ingest_taxonomia_use_case() -> IngestTaxonomiaUseCase:
    embedding_factory, monitoring, model = _embedding_deps()
    return IngestTaxonomiaUseCase(
        repository=get_fraud_knowledge_repository(),
        embedding_unit_of_work_factory=embedding_factory,
        monitoring=monitoring,
        embedding_model=model,
        id_generator=get_id_generator(),
    )


def get_ingest_modus_operandi_use_case() -> IngestModusOperandiUseCase:
    embedding_factory, monitoring, model = _embedding_deps()
    return IngestModusOperandiUseCase(
        repository=get_fraud_knowledge_repository(),
        embedding_unit_of_work_factory=embedding_factory,
        monitoring=monitoring,
        embedding_model=model,
        id_generator=get_id_generator(),
    )


def get_ingest_similar_case_use_case() -> IngestSimilarCaseUseCase:
    embedding_factory, monitoring, model = _embedding_deps()
    return IngestSimilarCaseUseCase(
        repository=get_fraud_knowledge_repository(),
        embedding_unit_of_work_factory=embedding_factory,
        monitoring=monitoring,
        embedding_model=model,
        id_generator=get_id_generator(),
    )


def get_ingest_flag_use_case() -> IngestFlagUseCase:
    embedding_factory, monitoring, model = _embedding_deps()
    return IngestFlagUseCase(
        repository=get_fraud_knowledge_repository(),
        embedding_unit_of_work_factory=embedding_factory,
        monitoring=monitoring,
        embedding_model=model,
        id_generator=get_id_generator(),
    )


def get_delete_taxonomia_use_case() -> DeleteTaxonomiaUseCase:
    return DeleteTaxonomiaUseCase(get_fraud_knowledge_repository())


def get_delete_modus_operandi_use_case() -> DeleteModusOperandiUseCase:
    return DeleteModusOperandiUseCase(get_fraud_knowledge_repository())


def get_delete_similar_case_use_case() -> DeleteSimilarCaseUseCase:
    return DeleteSimilarCaseUseCase(get_fraud_knowledge_repository())


def get_delete_flag_use_case() -> DeleteFlagUseCase:
    return DeleteFlagUseCase(get_fraud_knowledge_repository())


def get_list_fraud_knowledge_documents_use_case() -> ListFraudKnowledgeDocumentsUseCase:
    return ListFraudKnowledgeDocumentsUseCase(get_fraud_knowledge_repository())


def get_search_fraud_knowledge_use_case() -> SearchFraudKnowledgeUseCase:
    # Local import: vector_store_instance_factory imports this module at
    # top level (for the ingest use cases PromoteVectorStoreInstanceUseCase
    # needs) - importing it back at module level here would cycle.
    from src.infrastructure.entrypoint.api.factories.vector_store_instance_factory import (
        get_vector_store_instance_repository,
    )

    return SearchFraudKnowledgeUseCase(
        get_fraud_knowledge_search_port(), get_vector_store_instance_repository()
    )


def get_get_related_fraud_knowledge_use_case() -> GetRelatedFraudKnowledgeUseCase:
    return GetRelatedFraudKnowledgeUseCase(get_fraud_knowledge_relations_port())
