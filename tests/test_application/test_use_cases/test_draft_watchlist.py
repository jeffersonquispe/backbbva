from datetime import UTC, datetime

from src.application.ports.personal_data_masker_port import (
    MaskedPersonalData,
    PersonalDataMasker,
)
from src.application.ports.watchlist_port import Watchlist, WatchlistType
from src.application.use_cases.agent.draft_watchlist import _diff, _provenance, _verify


class _Masker(PersonalDataMasker):
    def mask(self, text: str) -> MaskedPersonalData:
        return MaskedPersonalData(text=text, counts={})


class _Entries:
    def __init__(self, rows: list[Watchlist]) -> None:
        self.rows = rows

    def list(self, **kwargs) -> list[Watchlist]:
        return self.rows


def _entry(identifier: str, name: str) -> Watchlist:
    now = datetime.now(UTC)
    return Watchlist(identifier, name, "Description", WatchlistType.BLACKLIST, now, now)


def test_watchlist_verifier_accepts_valid_metadata_and_rejects_duplicates() -> None:
    entries = _Entries([_entry("existing", "Sanctions list")])
    draft = {
        "name": "New list",
        "description": "List description",
        "list_type": "blacklist",
    }
    checks = _verify(draft, target_id=None, entries=entries, leaked=0)
    assert checks == [
        ("schema", "PASS", None),
        ("duplicates", "PASS", None),
        ("leakage", "PASS", None),
    ]

    duplicate = {**draft, "name": "  SANCTIONS   LIST "}
    checks = _verify(duplicate, target_id=None, entries=entries, leaked=0)
    assert checks[1] == ("duplicates", "FAIL", "DUPLICATE_WATCHLIST")


def test_watchlist_verifier_rejects_invalid_schema_and_redacted_content() -> None:
    checks = _verify(
        {"name": "", "description": "x" * 1001, "list_type": "unknown"},
        target_id=None,
        entries=_Entries([]),
        leaked=1,
    )
    assert checks == [
        ("schema", "FAIL", "DRAFT_SCHEMA_INVALID"),
        ("duplicates", "PASS", None),
        ("leakage", "FAIL", "PERSONAL_DATA_REDACTED"),
    ]


def test_watchlist_diff_and_provenance_are_field_specific_and_grounded() -> None:
    old = {"name": "Old", "description": "Existing", "list_type": "blacklist"}
    draft = {**old, "name": "New"}
    assert _diff(old, draft) == {"name": {"before": "Old", "after": "New"}}
    assert _provenance(
        {"name": {"source_quote": "make it New"}}, "Please make it New", "message-1"
    )["name"] == {
        "source": "user_input",
        "source_message_id": "message-1",
        "source_quote": "make it New",
    }
    assert (
        _provenance(
            {"name": {"source_quote": "invented"}}, "Please make it New", "message-1"
        )["name"]["source"]
        == "inferred"
    )
