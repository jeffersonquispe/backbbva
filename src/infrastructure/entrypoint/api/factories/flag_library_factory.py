from __future__ import annotations

from functools import lru_cache

from src.application.ports.embedding_unit_of_work_factory_port import (
    EmbeddingUnitOfWorkFactory,
)
from src.application.ports.flag_library_port import FlagLibraryRepository
from src.application.ports.monitoring_port import MonitoringPort
from src.application.use_cases.flag_library.create_flag_library_entry import (
    CreateFlagLibraryEntryUseCase,
)
from src.application.use_cases.flag_library.delete_flag_library_entry import (
    DeleteFlagLibraryEntryUseCase,
)
from src.application.use_cases.flag_library.list_flag_library_entries import (
    ListFlagLibraryEntriesUseCase,
)
from src.application.use_cases.flag_library.update_flag_library_entry import (
    UpdateFlagLibraryEntryUseCase,
)
from src.infrastructure.core.config import genai_config
from src.infrastructure.core.runtime.system_clock import get_clock
from src.infrastructure.core.runtime.uuid_generator import get_id_generator
from src.infrastructure.embedding.langchain import get_embedding_unit_of_work_factory
from src.infrastructure.monitoring.opentelemetry import get_monitoring
from src.infrastructure.persistence.database.dynamodb.repositories.flag_library_repository import (
    DynamoFlagLibraryRepository,
)


@lru_cache
def get_flag_library_repository() -> FlagLibraryRepository:
    return DynamoFlagLibraryRepository()


def _embedding_deps() -> tuple[EmbeddingUnitOfWorkFactory, MonitoringPort, str]:
    return (
        get_embedding_unit_of_work_factory(),
        get_monitoring(),
        genai_config.EMBEDDING_MODEL,
    )


def get_create_flag_library_entry_use_case() -> CreateFlagLibraryEntryUseCase:
    embedding_factory, monitoring, model = _embedding_deps()
    return CreateFlagLibraryEntryUseCase(
        get_flag_library_repository(),
        embedding_unit_of_work_factory=embedding_factory,
        monitoring=monitoring,
        embedding_model=model,
        clock=get_clock(),
        id_generator=get_id_generator(),
    )


def get_list_flag_library_entries_use_case() -> ListFlagLibraryEntriesUseCase:
    return ListFlagLibraryEntriesUseCase(get_flag_library_repository())


def get_update_flag_library_entry_use_case() -> UpdateFlagLibraryEntryUseCase:
    embedding_factory, monitoring, model = _embedding_deps()
    return UpdateFlagLibraryEntryUseCase(
        get_flag_library_repository(),
        embedding_unit_of_work_factory=embedding_factory,
        monitoring=monitoring,
        embedding_model=model,
    )


def get_delete_flag_library_entry_use_case() -> DeleteFlagLibraryEntryUseCase:
    return DeleteFlagLibraryEntryUseCase(get_flag_library_repository())
