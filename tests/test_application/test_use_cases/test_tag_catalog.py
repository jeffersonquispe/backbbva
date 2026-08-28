from __future__ import annotations

import pytest

from src.application.ports.tag_catalog_port import TagCategory, TagEntry
from src.application.use_cases.tag_catalog.create_tag import CreateTagUseCase
from src.application.use_cases.tag_catalog.delete_tag import DeleteTagUseCase
from src.application.use_cases.tag_catalog.list_tags import ListTagsUseCase
from src.application.use_cases.tag_catalog.update_tag import (
    TagNotFoundError,
    UpdateTagUseCase,
)


class InMemoryTagCatalogRepository:
    def __init__(self) -> None:
        self.items: dict[tuple[TagCategory, str], TagEntry] = {}

    def create(self, entry: TagEntry) -> TagEntry:
        self.items[(entry.category, entry.id)] = entry
        return entry

    def get(self, category: TagCategory, tag_id: str) -> TagEntry | None:
        return self.items.get((category, tag_id))

    def list_by_category(
        self, category: TagCategory, *, active_only: bool = False
    ) -> list[TagEntry]:
        entries = [e for (c, _), e in self.items.items() if c == category]
        if active_only:
            entries = [e for e in entries if e.active]
        return entries

    def update(
        self,
        category: TagCategory,
        tag_id: str,
        *,
        value: str | None = None,
        active: bool | None = None,
    ) -> TagEntry | None:
        current = self.items.get((category, tag_id))
        if current is None:
            return None
        updated = TagEntry(
            id=current.id,
            category=current.category,
            value=value if value is not None else current.value,
            active=active if active is not None else current.active,
            created_at=current.created_at,
            updated_at=current.updated_at,
        )
        self.items[(category, tag_id)] = updated
        return updated

    def delete(self, category: TagCategory, tag_id: str) -> None:
        self.items.pop((category, tag_id), None)


def test_create_tag_defaults_to_active() -> None:
    repo = InMemoryTagCatalogRepository()
    use_case = CreateTagUseCase(repo)

    entry = use_case.execute(TagCategory.TRIGGERED_RULE, "CUSTOMER - dg_no_digital")

    assert entry.category == TagCategory.TRIGGERED_RULE
    assert entry.value == "CUSTOMER - dg_no_digital"
    assert entry.active is True


def test_list_tags_filters_by_category_and_active_only() -> None:
    repo = InMemoryTagCatalogRepository()
    create = CreateTagUseCase(repo)
    list_tags = ListTagsUseCase(repo)

    rule = create.execute(TagCategory.TRIGGERED_RULE, "rule-a")
    create.execute(TagCategory.EVENT_TYPE, "event-a")
    repo.update(TagCategory.TRIGGERED_RULE, rule.id, active=False)

    assert len(list_tags.execute(TagCategory.TRIGGERED_RULE)) == 1
    assert list_tags.execute(TagCategory.TRIGGERED_RULE, active_only=True) == []
    assert len(list_tags.execute(TagCategory.EVENT_TYPE)) == 1


def test_update_tag_changes_value_and_active() -> None:
    repo = InMemoryTagCatalogRepository()
    create = CreateTagUseCase(repo)
    update = UpdateTagUseCase(repo)

    entry = create.execute(TagCategory.EVENT_TYPE, "old-value")
    updated = update.execute(TagCategory.EVENT_TYPE, entry.id, value="new-value")

    assert updated.value == "new-value"
    assert updated.active is True

    deactivated = update.execute(TagCategory.EVENT_TYPE, entry.id, active=False)
    assert deactivated.value == "new-value"
    assert deactivated.active is False


def test_update_unknown_tag_raises() -> None:
    repo = InMemoryTagCatalogRepository()
    update = UpdateTagUseCase(repo)

    with pytest.raises(TagNotFoundError):
        update.execute(TagCategory.EVENT_TYPE, "missing", value="x")


def test_delete_tag_removes_it() -> None:
    repo = InMemoryTagCatalogRepository()
    create = CreateTagUseCase(repo)
    delete = DeleteTagUseCase(repo)
    list_tags = ListTagsUseCase(repo)

    entry = create.execute(TagCategory.INTEGRATION_POINT, "ip-a")
    delete.execute(TagCategory.INTEGRATION_POINT, entry.id)

    assert list_tags.execute(TagCategory.INTEGRATION_POINT) == []
