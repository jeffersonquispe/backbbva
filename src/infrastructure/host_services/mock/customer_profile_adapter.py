from __future__ import annotations

import time

from src.application.ports.host_service_customer_port import (
    HostCustomerProfile,
    HostServiceCustomerProfilePort,
)


class MockHostServiceCustomerProfileAdapter(HostServiceCustomerProfilePort):
    def fetch_customer_profile(self, customer_id: str) -> HostCustomerProfile:
        time.sleep(0.05)
        return HostCustomerProfile(
            customer_name="Mock Customer",
            document_number=f"DOC-{customer_id}",
            mobile_number=None,
            date_of_birth=None,
            account_balance=None,
            available_balance=None,
            address=None,
        )
