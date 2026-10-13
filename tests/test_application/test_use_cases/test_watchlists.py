from __future__ import annotations

import pytest

from src.application.ports.watchlist_port import Watchlist, WatchlistType
from src.application.use_cases.watchlists.add_watchlist_elements import (
    AddWatchlistElementsUseCase,
)
from src.application.use_cases.watchlists.add_watchlist_elements import (
    WatchlistNotFoundError as AddElementsWatchlistNotFoundError,
)
from src.application.use_cases.watchlists.check_watchlist_membership import (
    CheckWatchlistMembershipUseCase,
)
from src.application.use_cases.watchlists.create_watchlist import CreateWatchlistUseCase
from src.application.use_cases.watchlists.delete_watchlist import DeleteWatchlistUseCase
from src.application.use_cases.watchlists.list_watchlist_elements import (
    ListWatchlistElementsUseCase,
)
from src.application.use_cases.watchlists.list_watchlists import ListWatchlistsUseCase
from src.application.use_cases.watchlists.remove_watchlist_elements import (
    RemoveWatchlistElementsUseCase,
)
from src.application.use_cases.watchlists.update_watchlist import (
    UpdateWatchlistUseCase,
    WatchlistNotFoundError,
)


class InMemoryWatchlistRepository:
    """Mirrors DynamoWatchlistRepository's element model: values live in a
    separate (watchlist_id, normalized value) map, not as a field on
    Watchlist - same shape a "gigantic" list needs in Dynamo, just a dict
    here instead of a table."""

    def __init__(self) -> None:
        self.items: dict[str, Watchlist] = {}
        self.elements: dict[str, dict[str, str]] = {}  # watchlist_id -> {norm: raw}

    def create(self, watchlist: Watchlist) -> Watchlist:
        self.items[watchlist.id] = watchlist
        self.elements.setdefault(watchlist.id, {})
        return watchlist

    def get(self, watchlist_id: str) -> Watchlist | None:
        watchlist = self.items.get(watchlist_id)
        if watchlist is None:
            return None
        watchlist.element_count = len(self.elements.get(watchlist_id, {}))
        return watchlist

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
        for entry in entries:
            entry.element_count = len(self.elements.get(entry.id, {}))
        return entries

    def update(
        self,
        watchlist_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
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
            active=active if active is not None else current.active,
            created_at=current.created_at,
            updated_at=current.updated_at,
        )
        self.items[watchlist_id] = updated
        updated.element_count = len(self.elements.get(watchlist_id, {}))
        return updated

    def delete(self, watchlist_id: str) -> None:
        self.items.pop(watchlist_id, None)
        self.elements.pop(watchlist_id, None)

    def add_elements(self, watchlist_id: str, values: list[str]) -> int:
        bucket = self.elements.setdefault(watchlist_id, {})
        normalized = {v.strip().casefold(): v.strip() for v in values if v.strip()}
        bucket.update(normalized)
        return len(normalized)

    def remove_elements(self, watchlist_id: str, values: list[str]) -> int:
        bucket = self.elements.setdefault(watchlist_id, {})
        normalized = {v.strip().casefold() for v in values if v.strip()}
        removed = 0
        for key in normalized:
            if bucket.pop(key, None) is not None:
                removed += 1
        return removed

    def count_elements(self, watchlist_id: str) -> int:
        return len(self.elements.get(watchlist_id, {}))

    def list_elements(
        self, watchlist_id: str, *, limit: int = 100, cursor: str | None = None
    ) -> tuple[list[str], str | None]:
        values = list(self.elements.get(watchlist_id, {}).values())
        start = int(cursor) if cursor else 0
        page = values[start : start + limit]
        next_cursor = str(start + limit) if start + limit < len(values) else None
        return page, next_cursor

    def elements_containing(self, watchlist_ids: list[str], value: str) -> set[str]:
        normalized = value.strip().casefold()
        return {
            wid
            for wid in watchlist_ids
            if normalized in self.elements.get(wid, {})
        }


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
    assert watchlist.element_count == 2
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


def test_update_watchlist_changes_name_and_description_without_touching_elements() -> None:
    repo = InMemoryWatchlistRepository()
    create = CreateWatchlistUseCase(repo)
    update = UpdateWatchlistUseCase(repo)

    watchlist = create.execute("old-name", "old-desc", WatchlistType.WHITELIST, ["x"])
    updated = update.execute(watchlist.id, name="new-name", description="new-desc")

    assert updated.name == "new-name"
    assert updated.description == "new-desc"
    assert updated.element_count == 1
    assert updated.active is True

    deactivated = update.execute(watchlist.id, active=False)
    assert deactivated.name == "new-name"
    assert deactivated.active is False


def test_update_unknown_watchlist_raises() -> None:
    repo = InMemoryWatchlistRepository()
    update = UpdateWatchlistUseCase(repo)

    with pytest.raises(WatchlistNotFoundError):
        update.execute("missing", name="x")


def test_delete_watchlist_removes_it_and_its_elements() -> None:
    repo = InMemoryWatchlistRepository()
    create = CreateWatchlistUseCase(repo)
    delete = DeleteWatchlistUseCase(repo)
    list_watchlists = ListWatchlistsUseCase(repo)

    watchlist = create.execute("temp", "desc", WatchlistType.BLACKLIST, ["z"])
    delete.execute(watchlist.id)

    assert list_watchlists.execute() == []
    assert repo.elements.get(watchlist.id) is None


def test_add_elements_dedupes_and_is_incremental() -> None:
    repo = InMemoryWatchlistRepository()
    create = CreateWatchlistUseCase(repo)
    add = AddWatchlistElementsUseCase(repo)

    watchlist = create.execute("Negra", "desc", WatchlistType.BLACKLIST)
    added_first = add.execute(watchlist.id, ["a", "b", " a "])
    added_second = add.execute(watchlist.id, ["b", "c"])

    assert added_first == 2  # "a" and " a " normalize to the same value
    assert added_second == 2
    assert repo.count_elements(watchlist.id) == 3


def test_add_elements_unknown_watchlist_raises() -> None:
    repo = InMemoryWatchlistRepository()
    add = AddWatchlistElementsUseCase(repo)

    with pytest.raises(AddElementsWatchlistNotFoundError):
        add.execute("missing", ["a"])


def test_remove_elements() -> None:
    repo = InMemoryWatchlistRepository()
    create = CreateWatchlistUseCase(repo)
    remove = RemoveWatchlistElementsUseCase(repo)

    watchlist = create.execute("Negra", "desc", WatchlistType.BLACKLIST, ["a", "b"])
    removed = remove.execute(watchlist.id, ["a", "missing"])

    assert removed == 1
    assert repo.count_elements(watchlist.id) == 1


def test_list_elements_paginates() -> None:
    repo = InMemoryWatchlistRepository()
    create = CreateWatchlistUseCase(repo)
    list_elements = ListWatchlistElementsUseCase(repo)

    watchlist = create.execute(
        "Negra", "desc", WatchlistType.BLACKLIST, [str(i) for i in range(5)]
    )

    first_page = list_elements.execute(watchlist.id, limit=2)
    assert len(first_page.values) == 2
    assert first_page.next_cursor is not None

    second_page = list_elements.execute(
        watchlist.id, limit=2, cursor=first_page.next_cursor
    )
    assert len(second_page.values) == 2

    all_values = set(first_page.values) | set(second_page.values)
    third_page = list_elements.execute(
        watchlist.id, limit=2, cursor=second_page.next_cursor
    )
    all_values |= set(third_page.values)
    assert third_page.next_cursor is None
    assert all_values == {"0", "1", "2", "3", "4"}


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


def test_check_membership_scales_with_watchlist_count_not_element_count() -> None:
    # Same point as the module docstring on CheckWatchlistMembershipUseCase:
    # a big list is one lookup, not a scan - this just asserts the observed
    # behavior a huge `elements` dict wouldn't change.
    repo = InMemoryWatchlistRepository()
    create = CreateWatchlistUseCase(repo)
    check = CheckWatchlistMembershipUseCase(repo)

    watchlist = create.execute(
        "Negra grande", "desc", WatchlistType.BLACKLIST, [str(i) for i in range(20_000)]
    )

    assert check.execute(WatchlistType.BLACKLIST, "19999")[0].watchlist_id == watchlist.id
    assert check.execute(WatchlistType.BLACKLIST, "20000") == []
