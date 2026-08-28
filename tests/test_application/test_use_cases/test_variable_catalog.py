from __future__ import annotations

import pytest

from src.application.ports.variable_catalog_port import VariableEntry
from src.application.use_cases.variable_catalog.create_variable import (
    CreateVariableUseCase,
)
from src.application.use_cases.variable_catalog.delete_variable import (
    DeleteVariableUseCase,
)
from src.application.use_cases.variable_catalog.list_variables import (
    ListVariablesUseCase,
)
from src.application.use_cases.variable_catalog.update_variable import (
    UpdateVariableUseCase,
    VariableNotFoundError,
)


class InMemoryVariableCatalogRepository:
    def __init__(self) -> None:
        self.items: dict[str, VariableEntry] = {}

    def create(self, entry: VariableEntry) -> VariableEntry:
        self.items[entry.id] = entry
        return entry

    def get(self, entry_id: str) -> VariableEntry | None:
        return self.items.get(entry_id)

    def list(self, *, active_only: bool = False) -> list[VariableEntry]:
        entries = list(self.items.values())
        if active_only:
            entries = [e for e in entries if e.active]
        return entries

    def update(
        self,
        entry_id: str,
        *,
        value: str | None = None,
        description: str | None = None,
        active: bool | None = None,
    ) -> VariableEntry | None:
        current = self.items.get(entry_id)
        if current is None:
            return None
        updated = VariableEntry(
            id=current.id,
            value=value if value is not None else current.value,
            description=description if description is not None else current.description,
            active=active if active is not None else current.active,
            created_at=current.created_at,
            updated_at=current.updated_at,
        )
        self.items[entry_id] = updated
        return updated

    def delete(self, entry_id: str) -> None:
        self.items.pop(entry_id, None)


def test_create_variable_defaults_to_active_and_empty_description() -> None:
    repo = InMemoryVariableCatalogRepository()
    use_case = CreateVariableUseCase(repo)

    entry = use_case.execute("Saldo")

    assert entry.value == "Saldo"
    assert entry.description == ""
    assert entry.active is True


def test_create_variable_with_description() -> None:
    repo = InMemoryVariableCatalogRepository()
    use_case = CreateVariableUseCase(repo)

    entry = use_case.execute("Altamira", "Score de riesgo del motor Altamira")

    assert entry.description == "Score de riesgo del motor Altamira"


def test_list_variables_filters_active_only() -> None:
    repo = InMemoryVariableCatalogRepository()
    create = CreateVariableUseCase(repo)
    list_variables = ListVariablesUseCase(repo)

    entry = create.execute("Saldo")
    create.execute("Documento")
    repo.update(entry.id, active=False)

    assert len(list_variables.execute()) == 2
    assert len(list_variables.execute(active_only=True)) == 1


def test_update_variable_changes_value_and_description() -> None:
    repo = InMemoryVariableCatalogRepository()
    create = CreateVariableUseCase(repo)
    update = UpdateVariableUseCase(repo)

    entry = create.execute("old-name")
    updated = update.execute(entry.id, value="new-name", description="nueva descripción")

    assert updated.value == "new-name"
    assert updated.description == "nueva descripción"
    assert updated.active is True

    deactivated = update.execute(entry.id, active=False)
    assert deactivated.value == "new-name"
    assert deactivated.active is False


def test_update_unknown_variable_raises() -> None:
    repo = InMemoryVariableCatalogRepository()
    update = UpdateVariableUseCase(repo)

    with pytest.raises(VariableNotFoundError):
        update.execute("missing", value="x")


def test_delete_variable_removes_it() -> None:
    repo = InMemoryVariableCatalogRepository()
    create = CreateVariableUseCase(repo)
    delete = DeleteVariableUseCase(repo)
    list_variables = ListVariablesUseCase(repo)

    entry = create.execute("Oficina")
    delete.execute(entry.id)

    assert list_variables.execute() == []
