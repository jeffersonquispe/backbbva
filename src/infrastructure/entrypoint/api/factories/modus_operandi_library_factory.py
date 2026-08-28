from __future__ import annotations

from functools import lru_cache

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
from src.infrastructure.persistence.database.dynamodb.repositories.modus_operandi_library_repository import (
    DynamoModusOperandiLibraryRepository,
)


@lru_cache
def get_modus_operandi_library_repository() -> DynamoModusOperandiLibraryRepository:
    return DynamoModusOperandiLibraryRepository()


def get_create_modus_operandi_library_entry_use_case() -> CreateModusOperandiLibraryEntryUseCase:
    return CreateModusOperandiLibraryEntryUseCase(get_modus_operandi_library_repository())


def get_list_modus_operandi_library_entries_use_case() -> ListModusOperandiLibraryEntriesUseCase:
    return ListModusOperandiLibraryEntriesUseCase(get_modus_operandi_library_repository())


def get_update_modus_operandi_library_entry_use_case() -> UpdateModusOperandiLibraryEntryUseCase:
    return UpdateModusOperandiLibraryEntryUseCase(get_modus_operandi_library_repository())


def get_delete_modus_operandi_library_entry_use_case() -> DeleteModusOperandiLibraryEntryUseCase:
    return DeleteModusOperandiLibraryEntryUseCase(get_modus_operandi_library_repository())
