from __future__ import annotations

import pytest

from src.application.ports.marcacion_catalog_port import MarcacionCategory, RiskLabel
from src.application.use_cases.marcacion_catalog.create_marcacion_category import (
    CreateMarcacionCategoryUseCase,
)
from src.application.use_cases.marcacion_catalog.delete_marcacion_category import (
    DeleteMarcacionCategoryUseCase,
)
from src.application.use_cases.marcacion_catalog.list_marcacion_categories import (
    ListMarcacionCategoriesUseCase,
)
from src.application.use_cases.marcacion_catalog.update_marcacion_category import (
    MarcacionCategoryNotFoundError,
    UpdateMarcacionCategoryUseCase,
)


class InMemoryMarcacionCatalogRepository:
    def __init__(self) -> None:
        self.items: dict[str, MarcacionCategory] = {}

    def create(self, entry: MarcacionCategory) -> MarcacionCategory:
        self.items[entry.id] = entry
        return entry

    def get(self, entry_id: str) -> MarcacionCategory | None:
        return self.items.get(entry_id)

    def list(self, *, active_only: bool = False) -> list[MarcacionCategory]:
        entries = list(self.items.values())
        if active_only:
            entries = [e for e in entries if e.active]
        return entries

    def update(
        self,
        entry_id: str,
        *,
        value: str | None = None,
        risk_label: RiskLabel | None = None,
        active: bool | None = None,
    ) -> MarcacionCategory | None:
        current = self.items.get(entry_id)
        if current is None:
            return None
        updated = MarcacionCategory(
            id=current.id,
            value=value if value is not None else current.value,
            risk_label=risk_label if risk_label is not None else current.risk_label,
            active=active if active is not None else current.active,
            created_at=current.created_at,
            updated_at=current.updated_at,
        )
        self.items[entry_id] = updated
        return updated

    def delete(self, entry_id: str) -> None:
        self.items.pop(entry_id, None)


def test_create_marcacion_category_defaults_to_active() -> None:
    repo = InMemoryMarcacionCatalogRepository()
    use_case = CreateMarcacionCategoryUseCase(repo)

    entry = use_case.execute("FR___ESTAFA", RiskLabel.RISK_SUSPECTED)

    assert entry.value == "FR___ESTAFA"
    assert entry.risk_label == RiskLabel.RISK_SUSPECTED
    assert entry.active is True


def test_list_marcacion_categories_filters_active_only() -> None:
    repo = InMemoryMarcacionCatalogRepository()
    create = CreateMarcacionCategoryUseCase(repo)
    list_categories = ListMarcacionCategoriesUseCase(repo)

    entry = create.execute("NF___FALSO_POSITIVO", RiskLabel.NO_RISK)
    create.execute("FR___ESTAFA", RiskLabel.RISK_SUSPECTED)
    repo.update(entry.id, active=False)

    assert len(list_categories.execute()) == 2
    assert len(list_categories.execute(active_only=True)) == 1


def test_update_marcacion_category_changes_value_and_risk_label() -> None:
    repo = InMemoryMarcacionCatalogRepository()
    create = CreateMarcacionCategoryUseCase(repo)
    update = UpdateMarcacionCategoryUseCase(repo)

    entry = create.execute("old-value", RiskLabel.NO_RISK)
    updated = update.execute(
        entry.id, value="new-value", risk_label=RiskLabel.RISK_SUSPECTED
    )

    assert updated.value == "new-value"
    assert updated.risk_label == RiskLabel.RISK_SUSPECTED
    assert updated.active is True

    deactivated = update.execute(entry.id, active=False)
    assert deactivated.value == "new-value"
    assert deactivated.active is False


def test_update_unknown_marcacion_category_raises() -> None:
    repo = InMemoryMarcacionCatalogRepository()
    update = UpdateMarcacionCategoryUseCase(repo)

    with pytest.raises(MarcacionCategoryNotFoundError):
        update.execute("missing", value="x")


def test_delete_marcacion_category_removes_it() -> None:
    repo = InMemoryMarcacionCatalogRepository()
    create = CreateMarcacionCategoryUseCase(repo)
    delete = DeleteMarcacionCategoryUseCase(repo)
    list_categories = ListMarcacionCategoriesUseCase(repo)

    entry = create.execute("ip-a", RiskLabel.NO_RISK)
    delete.execute(entry.id)

    assert list_categories.execute() == []
