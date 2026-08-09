from __future__ import annotations

import time

from src.application.ports.host_service_transaction_history_port import (
    HostServiceTransactionHistoryPort,
    TransactionHistoryEntry,
)


class MockHostServiceTransactionHistoryAdapter(
    HostServiceTransactionHistoryPort
):
    def fetch_transaction_history(
        self,
        customer_id: str,
        account_id: str | None,
    ) -> list[TransactionHistoryEntry]:
        time.sleep(0.05)
        return []
