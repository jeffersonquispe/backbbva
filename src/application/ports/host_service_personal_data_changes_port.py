from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PersonalDataChangeEntry:
    changed_field: str
    changed_at: str
    previous_value: str | None = None
    new_value: str | None = None


class HostServicePersonalDataChangesPort:
    def fetch_personal_data_changes(
        self,
        customer_id: str,
    ) -> list[PersonalDataChangeEntry]:
        raise NotImplementedError
