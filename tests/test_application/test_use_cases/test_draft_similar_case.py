from __future__ import annotations

import re
from types import SimpleNamespace

from src.application.ports.personal_data_masker_port import (
    MaskedPersonalData,
    PersonalDataMasker,
)
from src.application.use_cases.agent.draft_similar_case import (
    GenerateSimilarCaseDraftUseCase,
    _diff,
    _mask_tree,
    _normalize,
    _provenance,
)


class InMemoryEntries:
    def __init__(self, entries=()) -> None:
        self.entries = list(entries)

    def list(self):
        return self.entries


class InMemoryParents:
    def __init__(self, entries) -> None:
        self.entries = entries

    def get(self, entry_id):
        return self.entries.get(entry_id)


class InMemoryPersonalDataMasker(PersonalDataMasker):
    def mask(self, text: str) -> MaskedPersonalData:
        masked, count = re.subn(r"\b\d{8,10}\b", "[CC]", text)
        return MaskedPersonalData(masked, {"CC": count} if count else {})


def _use_case(*, cases=(), modus=None, taxonomies=None):
    use_case = object.__new__(GenerateSimilarCaseDraftUseCase)
    use_case._entries = InMemoryEntries(cases)
    use_case._modus = InMemoryParents(modus or {})
    use_case._taxonomies = InMemoryParents(taxonomies or {})
    return use_case


def test_similar_case_verifier_checks_parent_lineage_and_duplicates() -> None:
    use_case = _use_case(
        cases=[SimpleNamespace(id="case-old", text="Intento desde equipo nuevo", modus_operandi_library_id="mo-1")],
        modus={"mo-1": SimpleNamespace(active=True, taxonomy_library_id="tax-1")},
        taxonomies={"tax-1": SimpleNamespace(active=True)},
    )
    checks = use_case._verify({"text": "Intento desde equipo nuevo", "modus_operandi_library_id": "mo-1", "taxonomy_library_id": "tax-1"}, target_id=None, leaked=0)
    assert {name: status for name, status, _ in checks} == {
        "schema": "PASS", "parent_references": "PASS", "duplicates": "FAIL", "leakage": "PASS",
    }


def test_similar_case_verifier_rejects_inactive_or_mismatched_parents_and_pii() -> None:
    use_case = _use_case(
        modus={"mo-1": SimpleNamespace(active=True, taxonomy_library_id="tax-1")},
        taxonomies={"tax-other": SimpleNamespace(active=True)},
    )
    draft = _normalize({"text": "Titular 12345678 reporta fraude", "modus_operandi_library_id": "mo-1", "taxonomy_library_id": "tax-other"})
    masked, leaked = _mask_tree(draft, InMemoryPersonalDataMasker())
    checks = use_case._verify(masked, target_id=None, leaked=leaked)
    assert {name: status for name, status, _ in checks} == {
        "schema": "PASS", "parent_references": "FAIL", "duplicates": "PASS", "leakage": "FAIL",
    }
    assert masked["text"] == "Titular [CC] reporta fraude"


def test_similar_case_diff_and_provenance_keep_only_supported_fields() -> None:
    old = {"text": "Texto previo", "modus_operandi_library_id": "mo-1", "taxonomy_library_id": "tax-1"}
    draft = {**old, "text": "Texto actualizado"}
    assert _diff(old, draft) == {"text": {"before": "Texto previo", "after": "Texto actualizado"}}
    provenance = _provenance(
        {"text": {"source_quote": "Texto actualizado"}, "modus_operandi_library_id": {"source_quote": "inventado"}},
        "Texto actualizado y referencias exactas.", "message-1",
    )
    assert provenance["text"]["source"] == "user_input"
    assert provenance["modus_operandi_library_id"]["source"] == "inferred"
