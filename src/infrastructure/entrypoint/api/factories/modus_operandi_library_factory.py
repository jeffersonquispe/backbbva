from __future__ import annotations

from functools import lru_cache

from src.application.ports.embedding_port import EmbeddingUnitOfWorkFactory
from src.application.ports.monitoring_port import MonitoringPort
from src.application.use_cases.modus_operandi_library.create_modus_operandi_library_entry import (
    CreateModusOperandiLibraryEntryUseCase,
)
from src.application.use_cases.modus_operandi_library.delete_modus_operandi_library_entry import (
    DeleteModusOperandiLibraryEntryUseCase,
)
from src.application.use_cases.modus_operandi_library.list_modus_operandi_library_entries import (
    ListModusOperandiLibraryEntriesUseCase,
)
from src.application.use_cases.modus_operandi_library.update_modus_operandi_library_entry import (
    UpdateModusOperandiLibraryEntryUseCase,
)
from src.infrastructure.core.config import genai_config
from src.infrastructure.embedding.langchain import get_embedding_unit_of_work_factory
from src.infrastructure.monitoring.opentelemetry import get_monitoring
from src.infrastructure.persistence.database.dynamodb.repositories.modus_operandi_library_repository import (
    DynamoModusOperandiLibraryRepository,
)


@lru_cache
def get_modus_operandi_library_repository() -> DynamoModusOperandiLibraryRepository:
    return DynamoModusOperandiLibraryRepository()


def _embedding_deps() -> tuple[EmbeddingUnitOfWorkFactory, MonitoringPort, str]:
    return (
        get_embedding_unit_of_work_factory(),
        get_monitoring(),
        genai_config.EMBEDDING_MODEL,
    )


def get_create_modus_operandi_library_entry_use_case() -> (
    CreateModusOperandiLibraryEntryUseCase
):
    embedding_factory, monitoring, model = _embedding_deps()
    return CreateModusOperandiLibraryEntryUseCase(
        get_modus_operandi_library_repository(),
        embedding_unit_of_work_factory=embedding_factory,
        monitoring=monitoring,
        embedding_model=model,
    )


def get_list_modus_operandi_library_entries_use_case() -> (
    ListModusOperandiLibraryEntriesUseCase
):
    return ListModusOperandiLibraryEntriesUseCase(
        get_modus_operandi_library_repository()
    )


def get_update_modus_operandi_library_entry_use_case() -> (
    UpdateModusOperandiLibraryEntryUseCase
):
    embedding_factory, monitoring, model = _embedding_deps()
    return UpdateModusOperandiLibraryEntryUseCase(
        get_modus_operandi_library_repository(),
        embedding_unit_of_work_factory=embedding_factory,
        monitoring=monitoring,
        embedding_model=model,
    )


def get_delete_modus_operandi_library_entry_use_case() -> (
    DeleteModusOperandiLibraryEntryUseCase
):
    return DeleteModusOperandiLibraryEntryUseCase(
        get_modus_operandi_library_repository()
    )
