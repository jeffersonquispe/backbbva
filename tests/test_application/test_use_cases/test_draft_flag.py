from datetime import UTC, datetime
from types import SimpleNamespace

from src.application.use_cases.agent.draft_flag import _diff, _provenance, _verify
from src.domain.configurations.entities import FlagType
from src.domain.fraud_knowledge.library_entities import FlagLibraryEntry


class InMemoryFlagEntries:
    def __init__(self, entries: list[FlagLibraryEntry]) -> None:
        self.entries = entries

    def list(self, *, active_only: bool = False) -> list[FlagLibraryEntry]:
        return [entry for entry in self.entries if entry.active or not active_only]


class InMemoryModusOperandi:
    def __init__(self, identifiers: set[str]) -> None:
        self.identifiers = identifiers

    def get(self, entry_id: str):
        return (
            SimpleNamespace(id=entry_id, active=True)
            if entry_id in self.identifiers
            else None
        )


def test_flag_verifier_checks_duplicate_schema_and_active_parents() -> None:
    now = datetime.now(UTC)
    existing = FlagLibraryEntry(
        "flag-1",
        FlagType.RED,
        "Known flag",
        "Existing",
        now,
        now,
        modus_operandi_library_ids=["mo-1"],
    )
    entries = InMemoryFlagEntries([existing])
    parents = InMemoryModusOperandi({"mo-1"})
    duplicate = {
        "flag_type": "red",
        "name": " known   FLAG ",
        "description": "desc",
        "evolved_variables": ["channel"],
        "modus_operandi_library_ids": ["mo-1"],
    }
    checks = _verify(
        duplicate, target_id=None, entries=entries, modus_operandi=parents, leaked=0
    )
    assert {name: status for name, status, _ in checks} == {
        "schema": "PASS",
        "parent_references": "PASS",
        "duplicates": "FAIL",
        "leakage": "PASS",
    }

    invalid_parent = {
        **duplicate,
        "name": "New flag",
        "modus_operandi_library_ids": ["missing"],
    }
    checks = _verify(
        invalid_parent,
        target_id=None,
        entries=entries,
        modus_operandi=parents,
        leaked=1,
    )
    assert {name: status for name, status, _ in checks} == {
        "schema": "PASS",
        "parent_references": "FAIL",
        "duplicates": "PASS",
        "leakage": "FAIL",
    }


def test_flag_diff_and_provenance_are_grounded_per_field() -> None:
    old = {
        "flag_type": "red",
        "name": "Old",
        "description": "Same",
        "evolved_variables": [],
        "modus_operandi_library_ids": [],
    }
    draft = {**old, "description": "Updated"}
    assert _diff(old, draft) == {"description": {"before": "Same", "after": "Updated"}}
    provenance = _provenance(
        {"name": {"source_quote": "name New"}}, "Set the name New", "message-1"
    )
    assert provenance["name"] == {
        "source": "user_input",
        "source_message_id": "message-1",
        "source_quote": "name New",
    }
    assert provenance["description"]["source"] == "inferred"
