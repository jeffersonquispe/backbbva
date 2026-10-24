from __future__ import annotations

from abc import ABC
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TransactionHistoryEntry:
    event_id: str
    event_type: str
    event_time: str
    amount: float | None = None
    status: str | None = None
    alerts: str | None = None
    account_id: str | None = None
    integration_point: str | None = None
    channel: str | None = None
    counterparty: str | None = None
    additional_fields: dict[str, Any] = field(default_factory=dict)


class HostServiceTransactionHistoryPort(ABC):
    def fetch_transaction_history(
        self,
        customer_id: str,
        account_id: str | None,
    ) -> list[TransactionHistoryEntry]:
        raise NotImplementedError
