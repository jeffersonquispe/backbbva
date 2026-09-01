from __future__ import annotations

from functools import lru_cache

from src.application.use_cases.channel_library.create_channel_library_entry import (
    CreateChannelLibraryEntryUseCase,
)
from src.application.use_cases.channel_library.delete_channel_library_entry import (
    DeleteChannelLibraryEntryUseCase,
)
from src.application.use_cases.channel_library.list_channel_library_entries import (
    ListChannelLibraryEntriesUseCase,
)
from src.application.use_cases.channel_library.update_channel_library_entry import (
    UpdateChannelLibraryEntryUseCase,
)
from src.infrastructure.persistence.database.dynamodb.repositories.channel_library_repository import (
    DynamoChannelLibraryRepository,
)


@lru_cache
def get_channel_library_repository() -> DynamoChannelLibraryRepository:
    return DynamoChannelLibraryRepository()


def get_create_channel_library_entry_use_case() -> CreateChannelLibraryEntryUseCase:
    return CreateChannelLibraryEntryUseCase(get_channel_library_repository())


def get_list_channel_library_entries_use_case() -> ListChannelLibraryEntriesUseCase:
    return ListChannelLibraryEntriesUseCase(get_channel_library_repository())


def get_update_channel_library_entry_use_case() -> UpdateChannelLibraryEntryUseCase:
    return UpdateChannelLibraryEntryUseCase(get_channel_library_repository())


def get_delete_channel_library_entry_use_case() -> DeleteChannelLibraryEntryUseCase:
    return DeleteChannelLibraryEntryUseCase(get_channel_library_repository())
