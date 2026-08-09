from __future__ import annotations

import time

from src.application.ports.host_service_personal_data_changes_port import (
    HostServicePersonalDataChangesPort,
    PersonalDataChangeEntry,
)


class MockHostServicePersonalDataChangesAdapter(
    HostServicePersonalDataChangesPort
):
    def fetch_personal_data_changes(
        self,
        customer_id: str,
    ) -> list[PersonalDataChangeEntry]:
        time.sleep(0.05)
        return []
