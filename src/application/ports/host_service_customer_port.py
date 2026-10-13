from __future__ import annotations

from abc import ABC
from dataclasses import dataclass


@dataclass(frozen=True)
class HostCustomerProfile:
    customer_name: str | None = None
    document_number: str | None = None
    mobile_number: str | None = None
    date_of_birth: str | None = None
    account_balance: float | None = None
    available_balance: float | None = None
    address: str | None = None


class HostServiceCustomerProfilePort(ABC):
    def fetch_customer_profile(self, customer_id: str) -> HostCustomerProfile:
        raise NotImplementedError
