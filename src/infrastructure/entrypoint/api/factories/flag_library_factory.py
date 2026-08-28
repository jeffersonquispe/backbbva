from __future__ import annotations

from functools import lru_cache

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
from src.infrastructure.persistence.database.dynamodb.repositories.flag_library_repository import (
    DynamoFlagLibraryRepository,
)


@lru_cache
def get_flag_library_repository() -> DynamoFlagLibraryRepository:
    return DynamoFlagLibraryRepository()


def get_create_flag_library_entry_use_case() -> CreateFlagLibraryEntryUseCase:
    return CreateFlagLibraryEntryUseCase(get_flag_library_repository())


def get_list_flag_library_entries_use_case() -> ListFlagLibraryEntriesUseCase:
    return ListFlagLibraryEntriesUseCase(get_flag_library_repository())


def get_update_flag_library_entry_use_case() -> UpdateFlagLibraryEntryUseCase:
    return UpdateFlagLibraryEntryUseCase(get_flag_library_repository())


def get_delete_flag_library_entry_use_case() -> DeleteFlagLibraryEntryUseCase:
    return DeleteFlagLibraryEntryUseCase(get_flag_library_repository())
