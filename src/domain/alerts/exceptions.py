from __future__ import annotations


class MandatoryAlertDataMissingError(Exception):
    def __init__(self, missing_fields: list[str]) -> None:
        self.missing_fields = missing_fields
        super().__init__(
            "Alert payload missing mandatory fields: "
            + ", ".join(missing_fields)
        )
