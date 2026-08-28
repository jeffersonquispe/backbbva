from __future__ import annotations

from functools import lru_cache

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
from src.infrastructure.persistence.database.dynamodb.repositories.taxonomy_library_repository import (
    DynamoTaxonomyLibraryRepository,
)


@lru_cache
def get_taxonomy_library_repository() -> DynamoTaxonomyLibraryRepository:
    return DynamoTaxonomyLibraryRepository()


def get_create_taxonomy_library_entry_use_case() -> CreateTaxonomyLibraryEntryUseCase:
    return CreateTaxonomyLibraryEntryUseCase(get_taxonomy_library_repository())


def get_list_taxonomy_library_entries_use_case() -> ListTaxonomyLibraryEntriesUseCase:
    return ListTaxonomyLibraryEntriesUseCase(get_taxonomy_library_repository())


def get_update_taxonomy_library_entry_use_case() -> UpdateTaxonomyLibraryEntryUseCase:
    return UpdateTaxonomyLibraryEntryUseCase(get_taxonomy_library_repository())


def get_delete_taxonomy_library_entry_use_case() -> DeleteTaxonomyLibraryEntryUseCase:
    return DeleteTaxonomyLibraryEntryUseCase(get_taxonomy_library_repository())
