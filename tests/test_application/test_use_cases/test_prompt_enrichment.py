from __future__ import annotations

from src.application.ports.host_service_transaction_history_port import (
    TransactionHistoryEntry,
)
from src.application.use_cases.alerts.prompt_enrichment import (
    HISTORY_PROMPT_SAMPLE_SIZE,
    prompt_enrichment,
)


def _history(rows: int) -> list[TransactionHistoryEntry]:
    return [
        TransactionHistoryEntry(
            event_id=f"e{i}",
            event_type="paymentRT",
            event_time=f"2026-09-{(i % 27) + 1:02d}T10:00:00Z",
            amount=float(i),
        )
        for i in range(rows)
    ]


def test_a_long_history_reaches_the_prompt_as_a_short_sample() -> None:
    enrichment = {"transaction_history": _history(500), "customer_profile": {"a": 1}}

    result = prompt_enrichment(enrichment)

    history = result["transaction_history"]
    assert history["total_rows"] == 500
    assert len(history["sample"]) == HISTORY_PROMPT_SAMPLE_SIZE == 5
    assert result["customer_profile"] == {"a": 1}
    # The raw enrichment the history analysis reads is left untouched.
    assert len(enrichment["transaction_history"]) == 500


def test_enrichment_without_history_passes_through() -> None:
    assert prompt_enrichment({"aric_signals": {"is_rat": True}}) == {
        "aric_signals": {"is_rat": True}
    }
    assert prompt_enrichment({"transaction_history": []}) == {"transaction_history": []}
