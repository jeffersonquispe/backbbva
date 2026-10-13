from __future__ import annotations

from functools import lru_cache

from src.application.ports.watchlist_port import WatchlistRepository
from src.application.use_cases.watchlists.add_watchlist_elements import (
    AddWatchlistElementsUseCase,
)
from src.application.use_cases.watchlists.check_watchlist_membership import (
    CheckWatchlistMembershipUseCase,
)
from src.application.use_cases.watchlists.create_watchlist import CreateWatchlistUseCase
from src.application.use_cases.watchlists.delete_watchlist import DeleteWatchlistUseCase
from src.application.use_cases.watchlists.get_watchlist import GetWatchlistUseCase
from src.application.use_cases.watchlists.list_watchlist_elements import (
    ListWatchlistElementsUseCase,
)
from src.application.use_cases.watchlists.list_watchlists import ListWatchlistsUseCase
from src.application.use_cases.watchlists.remove_watchlist_elements import (
    RemoveWatchlistElementsUseCase,
)
from src.application.use_cases.watchlists.update_watchlist import UpdateWatchlistUseCase
from src.infrastructure.persistence.database.dynamodb.repositories.watchlist_repository import (
    DynamoWatchlistRepository,
)


@lru_cache
def get_watchlist_repository() -> WatchlistRepository:
    return DynamoWatchlistRepository()


def get_create_watchlist_use_case() -> CreateWatchlistUseCase:
    return CreateWatchlistUseCase(get_watchlist_repository())


def get_get_watchlist_use_case() -> GetWatchlistUseCase:
    return GetWatchlistUseCase(get_watchlist_repository())


def get_list_watchlists_use_case() -> ListWatchlistsUseCase:
    return ListWatchlistsUseCase(get_watchlist_repository())


def get_update_watchlist_use_case() -> UpdateWatchlistUseCase:
    return UpdateWatchlistUseCase(get_watchlist_repository())


def get_delete_watchlist_use_case() -> DeleteWatchlistUseCase:
    return DeleteWatchlistUseCase(get_watchlist_repository())


def get_check_watchlist_membership_use_case() -> CheckWatchlistMembershipUseCase:
    return CheckWatchlistMembershipUseCase(get_watchlist_repository())


def get_add_watchlist_elements_use_case() -> AddWatchlistElementsUseCase:
    return AddWatchlistElementsUseCase(get_watchlist_repository())


def get_remove_watchlist_elements_use_case() -> RemoveWatchlistElementsUseCase:
    return RemoveWatchlistElementsUseCase(get_watchlist_repository())


def get_list_watchlist_elements_use_case() -> ListWatchlistElementsUseCase:
    return ListWatchlistElementsUseCase(get_watchlist_repository())
