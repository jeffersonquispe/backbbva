from __future__ import annotations

from functools import lru_cache

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
from src.infrastructure.persistence.database.dynamodb.repositories.similar_case_library_repository import (
    DynamoSimilarCaseLibraryRepository,
)


@lru_cache
def get_similar_case_library_repository() -> DynamoSimilarCaseLibraryRepository:
    return DynamoSimilarCaseLibraryRepository()


def get_create_similar_case_library_entry_use_case() -> CreateSimilarCaseLibraryEntryUseCase:
    return CreateSimilarCaseLibraryEntryUseCase(get_similar_case_library_repository())


def get_list_similar_case_library_entries_use_case() -> ListSimilarCaseLibraryEntriesUseCase:
    return ListSimilarCaseLibraryEntriesUseCase(get_similar_case_library_repository())


def get_update_similar_case_library_entry_use_case() -> UpdateSimilarCaseLibraryEntryUseCase:
    return UpdateSimilarCaseLibraryEntryUseCase(get_similar_case_library_repository())


def get_delete_similar_case_library_entry_use_case() -> DeleteSimilarCaseLibraryEntryUseCase:
    return DeleteSimilarCaseLibraryEntryUseCase(get_similar_case_library_repository())
