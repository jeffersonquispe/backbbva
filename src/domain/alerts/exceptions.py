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


class AlertNotFoundError(Exception):
    def __init__(self, alert_id: str) -> None:
        self.alert_id = alert_id
        super().__init__(f"Alert not found: {alert_id}")


class AlertNotInAnalystQueueError(Exception):
    """Only ESCALATED alerts can be taken/resolved by a human analyst."""

    def __init__(self, alert_id: str, status: str) -> None:
        self.alert_id = alert_id
        self.status = status
        super().__init__(
            f"Alert {alert_id} is {status}, not waiting in the analyst queue."
        )


class AnalystBusyError(Exception):
    """An analyst holds at most one alert at a time - any other alert opens
    read-only until they resolve or release the one they have."""

    def __init__(self, held_alert_id: str | None) -> None:
        self.held_alert_id = held_alert_id
        super().__init__(
            "The analyst is already working on another alert"
            + (f" ({held_alert_id})" if held_alert_id else "")
            + "; resolve or release it first."
        )


class AlertAlreadyTakenError(Exception):
    def __init__(self, alert_id: str) -> None:
        self.alert_id = alert_id
        super().__init__(f"Alert {alert_id} is already being handled by another analyst.")


class NoAnalystCapacityError(Exception):
    """Every analyst the staffing matrix plans for this hour is busy (or
    analysts are switched off)."""

    def __init__(self) -> None:
        super().__init__("No analyst capacity available right now.")


class AlertNotHeldByAnalystError(Exception):
    def __init__(self, alert_id: str) -> None:
        self.alert_id = alert_id
        super().__init__(
            f"Alert {alert_id} is not currently taken by this analyst "
            "(never taken, released, or the 30-minute reservation expired)."
        )


class NoActiveVoicebotCallError(Exception):
    def __init__(self, alert_id: str) -> None:
        self.alert_id = alert_id
        super().__init__(
            f"No active voicebot call for alert {alert_id} (already "
            "released, expired, or never placed)."
        )


class SnapshotVersionConflictError(Exception):
    """The alert's metrics snapshot changed between read and write (another
    event won the race) - re-read and recompute the delta. Raised by
    MetricsRollupRepository.apply; RecordAlertMetricsEvent retries on it."""

    def __init__(self, alert_id: str, expected_version: int) -> None:
        self.alert_id = alert_id
        self.expected_version = expected_version
        super().__init__(
            f"Metrics snapshot of alert {alert_id} is no longer at version "
            f"{expected_version}."
        )


class InvalidFraudLabelError(ValueError):
    """A fraud-team review may only set fraud_label to fraud or no_fraud
    (pending is the absence of a decision, never a review outcome)."""

    def __init__(self, value: str) -> None:
        self.value = value
        super().__init__(
            f"Invalid fraud_label {value!r}: expected 'fraud' or 'no_fraud'."
        )
