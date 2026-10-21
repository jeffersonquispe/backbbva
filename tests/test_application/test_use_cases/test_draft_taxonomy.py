from __future__ import annotations

import re
from datetime import UTC, datetime

from src.application.ports.personal_data_masker_port import (
    MaskedPersonalData,
    PersonalDataMasker,
)
from src.application.use_cases.agent.draft_taxonomy import (
    _diff,
    _mask_tree,
    _normalize,
    _verify,
)
from src.domain.fraud_knowledge.library_entities import TaxonomyLibraryEntry


class InMemoryTaxonomyEntries:
    def __init__(self, entries: list[TaxonomyLibraryEntry]) -> None:
        self.entries = entries

    def list(self) -> list[TaxonomyLibraryEntry]:
        return self.entries


class InMemoryPersonalDataMasker(PersonalDataMasker):
    def mask(self, text: str) -> MaskedPersonalData:
        masked, count = re.subn(r"\b\d{8,10}\b", "[CC]", text)
        return MaskedPersonalData(masked, {"CC": count} if count else {})


def test_taxonomy_verifier_rejects_duplicate_schema_and_personal_data() -> None:
    existing = TaxonomyLibraryEntry(
        id="taxonomy-1", code="FRAUD-1", name="Suplantación", description="Fraude",
        variables=["channel"], examples=[], created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
    )
    draft = _normalize({"code": "FRAUD-1", "name": "Suplantación", "description": "CC 12345678", "variables": ["channel"], "examples": []})
    masked, leakage = _mask_tree(draft, InMemoryPersonalDataMasker())
    checks = _verify(masked, target_id=None, entries=InMemoryTaxonomyEntries([existing]), leaked=leakage)
    assert {name: status for name, status, _ in checks} == {
        "schema": "PASS", "duplicates": "FAIL", "leakage": "FAIL",
    }
    assert masked["description"] == "CC [CC]"


def test_taxonomy_diff_reports_only_changed_fields() -> None:
    current = {"code": "A", "name": "Antes", "description": "igual", "variables": ["x"], "examples": []}
    draft = {**current, "name": "Después"}
    assert _diff(current, draft) == {"name": {"before": "Antes", "after": "Después"}}
