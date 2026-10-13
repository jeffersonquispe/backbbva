from __future__ import annotations

from src.application.ports.host_service_transaction_history_port import (
    HostServiceTransactionHistoryPort,
    TransactionHistoryEntry,
)


class MockHostServiceTransactionHistoryAdapter(
    HostServiceTransactionHistoryPort
):
    """Deterministic local host history for the synthetic customers."""

    _TEST_CUSTOMERS = frozenset({"10264559", "8867889", "cust-1"})

    def fetch_transaction_history(
        self,
        customer_id: str,
        account_id: str | None,
    ) -> list[TransactionHistoryEntry]:
        if customer_id not in self._TEST_CUSTOMERS:
            return []
        return [
            TransactionHistoryEntry(
                event_id=f"{customer_id}-history-1",
                event_type="cardNRT",
                event_time="2026-10-08T14:30:00Z",
                amount=63800.0,
                status="APPROVED",
                alerts="no_alert",
                account_id=account_id or f"account-{customer_id}",
                integration_point="00 - Compra",
                channel="APP",
                counterparty="Mock Comercio 1",
            ),
            TransactionHistoryEntry(
                event_id=f"{customer_id}-history-2",
                event_type="transfer",
                event_time="2026-10-07T09:15:00Z",
                amount=125000.0,
                status="APPROVED",
                alerts="reviewed",
                account_id=account_id or f"account-{customer_id}",
                integration_point="01 - Transferencia",
                channel="WEB",
                counterparty="Mock Comercio 2",
            ),
        ]
