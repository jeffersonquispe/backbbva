from __future__ import annotations

import dataclasses
from typing import Any

from src.domain.alerts.transaction_history_selection import (
    summarize_transaction_history,
)

# Rows of the customer's transaction history an LLM prompt carries. The rest
# is analysed on the data (history analysis), not pasted into the prompt.
HISTORY_PROMPT_SAMPLE_SIZE = 5


def _serializable(value: Any) -> Any:
    return (
        dataclasses.asdict(value)
        if dataclasses.is_dataclass(value) and not isinstance(value, type)
        else value
    )


def prompt_enrichment(enrichment: dict[str, Any]) -> dict[str, Any]:
    """Enrichment as an LLM prompt should see it: the transaction history is
    reduced to its schema, size, period and a short sample."""
    result = {key: _serializable(value) for key, value in enrichment.items()}
    history = result.get("transaction_history")
    if history:
        result["transaction_history"] = summarize_transaction_history(
            history, sample_size=HISTORY_PROMPT_SAMPLE_SIZE
        )
    return result
