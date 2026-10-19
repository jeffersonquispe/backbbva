from __future__ import annotations

from functools import lru_cache

from src.application.ports.embedding_unit_of_work_factory_port import (
    EmbeddingUnitOfWorkFactory,
)
from src.application.ports.monitoring_port import MonitoringPort
from src.application.ports.taxonomy_library_port import TaxonomyLibraryRepository
from src.application.use_cases.taxonomy_library.create_taxonomy_library_entry import (
    CreateTaxonomyLibraryEntryUseCase,
)
from src.application.use_cases.taxonomy_library.delete_taxonomy_library_entry import (
    DeleteTaxonomyLibraryEntryUseCase,
)
from src.application.use_cases.taxonomy_library.list_taxonomy_library_entries import (
    ListTaxonomyLibraryEntriesUseCase,
)
from src.application.use_cases.taxonomy_library.update_taxonomy_library_entry import (
    UpdateTaxonomyLibraryEntryUseCase,
)
from src.infrastructure.core.config import genai_config
from src.infrastructure.core.runtime.system_clock import get_clock
from src.infrastructure.core.runtime.uuid_generator import get_id_generator
from src.infrastructure.embedding.langchain import get_embedding_unit_of_work_factory
from src.infrastructure.monitoring.opentelemetry import get_monitoring
from src.infrastructure.persistence.database.dynamodb.repositories.taxonomy_library_repository import (
    DynamoTaxonomyLibraryRepository,
)


@lru_cache
def get_taxonomy_library_repository() -> TaxonomyLibraryRepository:
    return DynamoTaxonomyLibraryRepository()


def _embedding_deps() -> tuple[EmbeddingUnitOfWorkFactory, MonitoringPort, str]:
    return (
        get_embedding_unit_of_work_factory(),
        get_monitoring(),
        genai_config.EMBEDDING_MODEL,
    )


def get_create_taxonomy_library_entry_use_case() -> CreateTaxonomyLibraryEntryUseCase:
    embedding_factory, monitoring, model = _embedding_deps()
    return CreateTaxonomyLibraryEntryUseCase(
        get_taxonomy_library_repository(),
        embedding_unit_of_work_factory=embedding_factory,
        monitoring=monitoring,
        embedding_model=model,
        clock=get_clock(),
        id_generator=get_id_generator(),
    )


def get_list_taxonomy_library_entries_use_case() -> ListTaxonomyLibraryEntriesUseCase:
    return ListTaxonomyLibraryEntriesUseCase(get_taxonomy_library_repository())


def get_update_taxonomy_library_entry_use_case() -> UpdateTaxonomyLibraryEntryUseCase:
    embedding_factory, monitoring, model = _embedding_deps()
    return UpdateTaxonomyLibraryEntryUseCase(
        get_taxonomy_library_repository(),
        embedding_unit_of_work_factory=embedding_factory,
        monitoring=monitoring,
        embedding_model=model,
    )


def get_delete_taxonomy_library_entry_use_case() -> DeleteTaxonomyLibraryEntryUseCase:
    return DeleteTaxonomyLibraryEntryUseCase(get_taxonomy_library_repository())
