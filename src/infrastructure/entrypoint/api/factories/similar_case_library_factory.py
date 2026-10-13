from __future__ import annotations

from functools import lru_cache

from src.application.ports.embedding_port import EmbeddingUnitOfWorkFactory
from src.application.ports.monitoring_port import MonitoringPort
from src.application.ports.similar_case_library_port import SimilarCaseLibraryRepository
from src.application.use_cases.similar_case_library.create_similar_case_library_entry import (
    CreateSimilarCaseLibraryEntryUseCase,
)
from src.application.use_cases.similar_case_library.delete_similar_case_library_entry import (
    DeleteSimilarCaseLibraryEntryUseCase,
)
from src.application.use_cases.similar_case_library.list_similar_case_library_entries import (
    ListSimilarCaseLibraryEntriesUseCase,
)
from src.application.use_cases.similar_case_library.update_similar_case_library_entry import (
    UpdateSimilarCaseLibraryEntryUseCase,
)
from src.infrastructure.core.config import genai_config
from src.infrastructure.embedding.langchain import get_embedding_unit_of_work_factory
from src.infrastructure.monitoring.opentelemetry import get_monitoring
from src.infrastructure.persistence.database.dynamodb.repositories.similar_case_library_repository import (
    DynamoSimilarCaseLibraryRepository,
)


@lru_cache
def get_similar_case_library_repository() -> SimilarCaseLibraryRepository:
    return DynamoSimilarCaseLibraryRepository()


def _embedding_deps() -> tuple[EmbeddingUnitOfWorkFactory, MonitoringPort, str]:
    return (
        get_embedding_unit_of_work_factory(),
        get_monitoring(),
        genai_config.EMBEDDING_MODEL,
    )


def get_create_similar_case_library_entry_use_case() -> (
    CreateSimilarCaseLibraryEntryUseCase
):
    embedding_factory, monitoring, model = _embedding_deps()
    return CreateSimilarCaseLibraryEntryUseCase(
        get_similar_case_library_repository(),
        embedding_unit_of_work_factory=embedding_factory,
        monitoring=monitoring,
        embedding_model=model,
    )


def get_list_similar_case_library_entries_use_case() -> (
    ListSimilarCaseLibraryEntriesUseCase
):
    return ListSimilarCaseLibraryEntriesUseCase(get_similar_case_library_repository())


def get_update_similar_case_library_entry_use_case() -> (
    UpdateSimilarCaseLibraryEntryUseCase
):
    embedding_factory, monitoring, model = _embedding_deps()
    return UpdateSimilarCaseLibraryEntryUseCase(
        get_similar_case_library_repository(),
        embedding_unit_of_work_factory=embedding_factory,
        monitoring=monitoring,
        embedding_model=model,
    )


def get_delete_similar_case_library_entry_use_case() -> (
    DeleteSimilarCaseLibraryEntryUseCase
):
    return DeleteSimilarCaseLibraryEntryUseCase(get_similar_case_library_repository())
