from __future__ import annotations


class MandatoryAlertDataMissingError(Exception):
    def __init__(self, missing_fields: list[str]) -> None:
        self.missing_fields = missing_fields
        super().__init__(
            "Alert payload missing mandatory fields: "
            + ", ".join(missing_fields)
        )


class AlertPayloadTooLargeError(Exception):
    """Raised before an alert payload reaches DynamoDB, which hard-caps a
    single item at 400KB. Datasets with large embedded fields (e.g. a
    customer's full transaction history as JSON in one CSV column - see
    csv_dataset_repository.py) can produce rows that would otherwise fail
    deep inside put_item with an opaque ValidationException."""

    def __init__(self, size_bytes: int, limit_bytes: int) -> None:
        self.size_bytes = size_bytes
        self.limit_bytes = limit_bytes
        super().__init__(
            f"Alert payload is {size_bytes:,} bytes, over the "
            f"{limit_bytes:,}-byte limit (DynamoDB's item size cap, minus "
            "headroom for the alert's other fields)."
        )
