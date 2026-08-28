from __future__ import annotations

import pytest

from src.application.ports.watchlist_port import Watchlist, WatchlistType
from src.application.use_cases.watchlists.check_watchlist_membership import (
    CheckWatchlistMembershipUseCase,
)
from src.application.use_cases.watchlists.create_watchlist import CreateWatchlistUseCase
from src.application.use_cases.watchlists.delete_watchlist import DeleteWatchlistUseCase
from src.application.use_cases.watchlists.list_watchlists import ListWatchlistsUseCase
from src.application.use_cases.watchlists.update_watchlist import (
    UpdateWatchlistUseCase,
    WatchlistNotFoundError,
)


class InMemoryWatchlistRepository:
    def __init__(self) -> None:
        self.items: dict[str, Watchlist] = {}

    def create(self, watchlist: Watchlist) -> Watchlist:
        self.items[watchlist.id] = watchlist
        return watchlist

    def get(self, watchlist_id: str) -> Watchlist | None:
        return self.items.get(watchlist_id)

    def list(
        self,
        *,
        list_type: WatchlistType | None = None,
        active_only: bool = False,
    ) -> list[Watchlist]:
        entries = list(self.items.values())
        if list_type is not None:
            entries = [e for e in entries if e.list_type == list_type]
        if active_only:
            entries = [e for e in entries if e.active]
        return entries

    def update(
        self,
        watchlist_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        elements: list[str] | None = None,
        active: bool | None = None,
    ) -> Watchlist | None:
        current = self.items.get(watchlist_id)
        if current is None:
            return None
        updated = Watchlist(
            id=current.id,
            name=name if name is not None else current.name,
            description=description if description is not None else current.description,
            list_type=current.list_type,
            elements=elements if elements is not None else current.elements,
            active=active if active is not None else current.active,
            created_at=current.created_at,
            updated_at=current.updated_at,
        )
        self.items[watchlist_id] = updated
        return updated

    def delete(self, watchlist_id: str) -> None:
        self.items.pop(watchlist_id, None)


def test_create_watchlist_defaults_to_active_with_given_elements() -> None:
    repo = InMemoryWatchlistRepository()
    use_case = CreateWatchlistUseCase(repo)

    watchlist = use_case.execute(
        "Cuentas mula conocidas",
        "Cuentas identificadas como puente para transferencias ilícitas.",
        WatchlistType.BLACKLIST,
        ["1234567890", "0987654321"],
    )

    assert watchlist.name == "Cuentas mula conocidas"
    assert watchlist.list_type == WatchlistType.BLACKLIST
    assert watchlist.elements == ["1234567890", "0987654321"]
    assert watchlist.active is True


def test_list_watchlists_filters_by_type_and_active_only() -> None:
    repo = InMemoryWatchlistRepository()
    create = CreateWatchlistUseCase(repo)
    list_watchlists = ListWatchlistsUseCase(repo)

    black = create.execute("Negra", "desc", WatchlistType.BLACKLIST, ["a"])
    create.execute("Blanca", "desc", WatchlistType.WHITELIST, ["b"])
    repo.update(black.id, active=False)

    assert len(list_watchlists.execute()) == 2
    assert len(list_watchlists.execute(list_type=WatchlistType.WHITELIST)) == 1
    assert list_watchlists.execute(active_only=True)[0].list_type == WatchlistType.WHITELIST


def test_update_watchlist_changes_name_description_and_elements() -> None:
    repo = InMemoryWatchlistRepository()
    create = CreateWatchlistUseCase(repo)
    update = UpdateWatchlistUseCase(repo)

    watchlist = create.execute("old-name", "old-desc", WatchlistType.WHITELIST, ["x"])
    updated = update.execute(
        watchlist.id, name="new-name", description="new-desc", elements=["x", "y"]
    )

    assert updated.name == "new-name"
    assert updated.description == "new-desc"
    assert updated.elements == ["x", "y"]
    assert updated.active is True

    deactivated = update.execute(watchlist.id, active=False)
    assert deactivated.name == "new-name"
    assert deactivated.active is False


def test_update_unknown_watchlist_raises() -> None:
    repo = InMemoryWatchlistRepository()
    update = UpdateWatchlistUseCase(repo)

    with pytest.raises(WatchlistNotFoundError):
        update.execute("missing", name="x")


def test_delete_watchlist_removes_it() -> None:
    repo = InMemoryWatchlistRepository()
    create = CreateWatchlistUseCase(repo)
    delete = DeleteWatchlistUseCase(repo)
    list_watchlists = ListWatchlistsUseCase(repo)

    watchlist = create.execute("temp", "desc", WatchlistType.BLACKLIST, ["z"])
    delete.execute(watchlist.id)

    assert list_watchlists.execute() == []


def test_check_membership_matches_case_and_whitespace_insensitively() -> None:
    repo = InMemoryWatchlistRepository()
    create = CreateWatchlistUseCase(repo)
    check = CheckWatchlistMembershipUseCase(repo)

    create.execute(
        "Cuentas mula conocidas", "desc", WatchlistType.BLACKLIST, ["1234567890"]
    )

    matches = check.execute(WatchlistType.BLACKLIST, " 1234567890 ")
    assert len(matches) == 1
    assert matches[0].watchlist_name == "Cuentas mula conocidas"

    assert check.execute(WatchlistType.BLACKLIST, "not-there") == []
    assert check.execute(WatchlistType.WHITELIST, "1234567890") == []


def test_check_membership_ignores_inactive_watchlists() -> None:
    repo = InMemoryWatchlistRepository()
    create = CreateWatchlistUseCase(repo)
    update = UpdateWatchlistUseCase(repo)
    check = CheckWatchlistMembershipUseCase(repo)

    watchlist = create.execute("desactivada", "desc", WatchlistType.BLACKLIST, ["a"])
    update.execute(watchlist.id, active=False)

    assert check.execute(WatchlistType.BLACKLIST, "a") == []
