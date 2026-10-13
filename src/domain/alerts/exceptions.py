from __future__ import annotations

from src.domain import (
    ConflictError,
    DomainException,
    ValidationError,
)


class MandatoryAlertDataMissingError(ValidationError):
    def __init__(self, missing_fields: list[str]) -> None:
        self.missing_fields = missing_fields
        super().__init__(
            "Alert payload missing mandatory fields: " + ", ".join(missing_fields)
        )


class NoActiveAlertSchemaError(DomainException):
    """The alert cannot be processed without an approved schema version."""

    def __init__(self) -> None:
        super().__init__(
            "No active alert schema is configured; the alert was escalated "
            "to an analyst because it cannot be safely pre-processed."
        )


class AlertFieldTypeMismatchError(ValidationError):
    def __init__(self, field: str, expected: str, value: object) -> None:
        self.field = field
        self.expected = expected
        self.value = value
        super().__init__(
            f"Alert field {field!r} has an invalid type: expected {expected}, "
            f"got {type(value).__name__}."
        )


class AlertPayloadTooLargeError(ValidationError):
    """An alert payload exceeds the configured storage limit."""

    def __init__(self, size_bytes: int, limit_bytes: int) -> None:
        self.size_bytes = size_bytes
        self.limit_bytes = limit_bytes
        super().__init__(
            f"Alert payload is {size_bytes:,} bytes, over the "
            f"{limit_bytes:,}-byte limit."
        )


class AlertNotFoundError(DomainException):
    def __init__(self, alert_id: str) -> None:
        self.alert_id = alert_id
        super().__init__(f"Alert not found: {alert_id}")


class AlertNotInAnalystQueueError(ConflictError):
    """Only ESCALATED alerts can be taken/resolved by a human analyst."""

    def __init__(self, alert_id: str, status: str) -> None:
        self.alert_id = alert_id
        self.status = status
        super().__init__(
            f"Alert {alert_id} is {status}, not waiting in the analyst queue."
        )


class AnalystBusyError(ConflictError):
    """An analyst holds at most one alert at a time - any other alert opens
    read-only until they resolve or release the one they have."""

    def __init__(self, held_alert_id: str | None) -> None:
        self.held_alert_id = held_alert_id
        super().__init__(
            "The analyst is already working on another alert"
            + (f" ({held_alert_id})" if held_alert_id else "")
            + "; resolve or release it first."
        )


class AlertAlreadyTakenError(ConflictError):
    def __init__(self, alert_id: str) -> None:
        self.alert_id = alert_id
        super().__init__(
            f"Alert {alert_id} is already being handled by another analyst."
        )


class NoAnalystCapacityError(ConflictError):
    """Every analyst the staffing matrix plans for this hour is busy (or
    analysts are switched off)."""

    def __init__(self) -> None:
        super().__init__("No analyst capacity available right now.")


class AlertNotHeldByAnalystError(ConflictError):
    def __init__(self, alert_id: str) -> None:
        self.alert_id = alert_id
        super().__init__(
            f"Alert {alert_id} is not currently taken by this analyst "
            "(never taken, released, or the 30-minute reservation expired)."
        )


class NoActiveVoicebotCallError(ConflictError):
    def __init__(self, alert_id: str) -> None:
        self.alert_id = alert_id
        super().__init__(
            f"No active voicebot call for alert {alert_id} (already "
            "released, expired, or never placed)."
        )


class SnapshotVersionConflictError(ConflictError):
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


class InvalidFraudLabelError(ValidationError):
    """A fraud-team review may only set fraud_label to fraud or no_fraud
    (pending is the absence of a decision, never a review outcome)."""

    def __init__(self, value: str) -> None:
        self.value = value
        super().__init__(
            f"Invalid fraud_label {value!r}: expected 'fraud' or 'no_fraud'."
        )


class AdversarialFeedbackLimitExceededError(DomainException):
    """Raised when an adversarial review step keeps rejecting its paired
    primary step (classification, or detector) past the workflow's/
    segment's allowed feedback loop-backs, so the alert must escalate to a
    human analyst instead of looping forever."""
