from __future__ import annotations

import pytest

from src.application.ports.resolution_method_catalog_port import ResolutionMethod
from src.application.use_cases.resolution_method_catalog.create_resolution_method import (
    CreateResolutionMethodUseCase,
)
from src.application.use_cases.resolution_method_catalog.delete_resolution_method import (
    DeleteResolutionMethodUseCase,
)
from src.application.use_cases.resolution_method_catalog.list_resolution_methods import (
    ListResolutionMethodsUseCase,
)
from src.application.use_cases.resolution_method_catalog.update_resolution_method import (
    ResolutionMethodNotFoundError,
    UpdateResolutionMethodUseCase,
)
from src.domain.configurations.entities import (
    ResolutionTag,
)


class InMemoryResolutionMethodCatalogRepository:
    def __init__(self) -> None:
        self.items: dict[str, ResolutionMethod] = {}

    def create(self, entry: ResolutionMethod) -> ResolutionMethod:
        self.items[entry.id] = entry
        return entry

    def get(self, entry_id: str) -> ResolutionMethod | None:
        return self.items.get(entry_id)

    def list(self, *, active_only: bool = False) -> list[ResolutionMethod]:
        entries = list(self.items.values())
        if active_only:
            entries = [e for e in entries if e.active]
        return entries

    def update(
        self,
        entry_id: str,
        *,
        value: str | None = None,
        resolution_tag: ResolutionTag | None = None,
        active: bool | None = None,
    ) -> ResolutionMethod | None:
        current = self.items.get(entry_id)
        if current is None:
            return None
        updated = ResolutionMethod(
            id=current.id,
            value=value if value is not None else current.value,
            resolution_tag=resolution_tag
            if resolution_tag is not None
            else current.resolution_tag,
            active=active if active is not None else current.active,
            created_at=current.created_at,
            updated_at=current.updated_at,
        )
        self.items[entry_id] = updated
        return updated

    def delete(self, entry_id: str) -> None:
        self.items.pop(entry_id, None)


def test_create_resolution_method_defaults_to_active() -> None:
    repo = InMemoryResolutionMethodCatalogRepository()
    use_case = CreateResolutionMethodUseCase(repo)

    entry = use_case.execute(
        "Escalar a analista senior", ResolutionTag.SCALE_TO_ANALYST
    )

    assert entry.value == "Escalar a analista senior"
    assert entry.resolution_tag == ResolutionTag.SCALE_TO_ANALYST
    assert entry.active is True


def test_list_resolution_methods_filters_active_only() -> None:
    repo = InMemoryResolutionMethodCatalogRepository()
    create = CreateResolutionMethodUseCase(repo)
    list_methods = ListResolutionMethodsUseCase(repo)

    entry = create.execute("Escalar a analista", ResolutionTag.SCALE_TO_ANALYST)
    create.execute("Enviar a voicebot", ResolutionTag.SEND_TO_VOICEBOT)
    repo.update(entry.id, active=False)

    assert len(list_methods.execute()) == 2
    assert len(list_methods.execute(active_only=True)) == 1


def test_update_resolution_method_changes_value_and_tag() -> None:
    repo = InMemoryResolutionMethodCatalogRepository()
    create = CreateResolutionMethodUseCase(repo)
    update = UpdateResolutionMethodUseCase(repo)

    entry = create.execute("old-name", ResolutionTag.SCALE_TO_ANALYST)
    updated = update.execute(
        entry.id, value="new-name", resolution_tag=ResolutionTag.HANDLE_BY_ARIA
    )

    assert updated.value == "new-name"
    assert updated.resolution_tag == ResolutionTag.HANDLE_BY_ARIA
    assert updated.active is True

    deactivated = update.execute(entry.id, active=False)
    assert deactivated.value == "new-name"
    assert deactivated.active is False


def test_update_unknown_resolution_method_raises() -> None:
    repo = InMemoryResolutionMethodCatalogRepository()
    update = UpdateResolutionMethodUseCase(repo)

    with pytest.raises(ResolutionMethodNotFoundError):
        update.execute("missing", value="x")


def test_delete_resolution_method_removes_it() -> None:
    repo = InMemoryResolutionMethodCatalogRepository()
    create = CreateResolutionMethodUseCase(repo)
    delete = DeleteResolutionMethodUseCase(repo)
    list_methods = ListResolutionMethodsUseCase(repo)

    entry = create.execute("Resolver con ARIA", ResolutionTag.HANDLE_BY_ARIA)
    delete.execute(entry.id)

    assert list_methods.execute() == []
