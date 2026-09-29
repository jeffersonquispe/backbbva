from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from src.application.ports.resource_reservation_port import (
    RESERVATION_TTL,
    AcquireResult,
    ReservationConflict,
    ReservationStatus,
    ReservedResource,
    ResourceReservation,
    ResourceReservationRepository,
)
from src.infrastructure.persistence.database.dynamodb.client import (
    get_dynamodb_resource,
)

logger = logging.getLogger(__name__)

LOCKS_TABLE_NAME = "resource_locks"
RESERVATIONS_TABLE_NAME = "resource_reservations"

# A lock is free when missing or past its expiry - the same predicate on
# every conditional put, so an expired holder never blocks anyone.
_FREE_CONDITION = "attribute_not_exists(#lock) OR expires_at <= :now"


def _slot_lock(slot: int) -> str:
    return f"slot#{slot:04d}"


def _alert_lock(alert_id: str) -> str:
    return f"alert#{alert_id}"


def _holder_lock(holder: str) -> str:
    return f"holder#{holder}"


class DynamoResourceReservationRepository(ResourceReservationRepository):
    """Two tables: `resource_locks` (pk resource, sk lock) holds the
    currently-claimed slot/alert/holder locks, so one Query per resource
    shows what is free; `resource_reservations` (pk id) keeps every
    reservation ever made, as the audit trail. try_acquire writes the locks
    and the record in one TransactWriteItems, so the quota holds under
    concurrent workers."""

    def __init__(self) -> None:
        resource = get_dynamodb_resource()
        # The resource's own client applies boto3's type (de)serializer, so
        # transact_write_items takes plain Python values, like Table calls.
        self._client = resource.meta.client
        self._locks = resource.Table(LOCKS_TABLE_NAME)
        self._reservations = resource.Table(RESERVATIONS_TABLE_NAME)

    def try_acquire(
        self,
        resource: ReservedResource,
        *,
        alert_id: str,
        holder: str,
        capacity: int,
        now: datetime,
        ttl: timedelta = RESERVATION_TTL,
    ) -> AcquireResult:
        now_ts = Decimal(str(now.timestamp()))
        locks = {
            item["lock"]: item
            for item in self._locks.query(
                KeyConditionExpression=Key("resource").eq(resource.value)
            ).get("Items", [])
        }

        def is_free(lock: str) -> bool:
            item = locks.get(lock)
            return item is None or Decimal(item["expires_at"]) <= now_ts

        alert_lock = _alert_lock(alert_id)
        # A voicebot call is held by the alert itself - one lock covers both.
        holder_lock = _holder_lock(holder) if holder != alert_id else None
        if not is_free(alert_lock):
            return AcquireResult(None, ReservationConflict.ALERT_TAKEN)
        if holder_lock is not None and not is_free(holder_lock):
            return AcquireResult(None, ReservationConflict.HOLDER_BUSY)

        free_slots = [n for n in range(capacity) if is_free(_slot_lock(n))]
        for slot in free_slots:
            reservation = ResourceReservation(
                id=str(uuid.uuid4()),
                resource=resource,
                alert_id=alert_id,
                holder=holder,
                slot=slot,
                reserved_at=now,
                expires_at=now + ttl,
            )
            lock_names = [_slot_lock(slot), alert_lock]
            if holder_lock is not None:
                lock_names.append(holder_lock)
            try:
                self._client.transact_write_items(
                    TransactItems=[
                        *(
                            self._put_lock(resource, lock, reservation, now_ts)
                            for lock in lock_names
                        ),
                        {
                            "Put": {
                                "TableName": RESERVATIONS_TABLE_NAME,
                                "Item": _to_dynamo(_to_item(reservation)),
                            }
                        },
                    ]
                )
            except ClientError as exc:
                if exc.response["Error"]["Code"] != "TransactionCanceledException":
                    raise
                failed = _failed_indexes(exc)
                if 1 in failed:
                    return AcquireResult(None, ReservationConflict.ALERT_TAKEN)
                if 2 in failed and holder_lock is not None:
                    return AcquireResult(None, ReservationConflict.HOLDER_BUSY)
                continue  # someone took this slot first - try the next one
            self._expire_superseded(
                [locks.get(lock) for lock in lock_names], reservation.id, now
            )
            return AcquireResult(reservation)
        return AcquireResult(None, ReservationConflict.NO_CAPACITY)

    def release(
        self,
        reservation_id: str,
        *,
        reason: str,
        now: datetime,
        detail: dict[str, Any] | None = None,
    ) -> ResourceReservation | None:
        reservation = self.get(reservation_id)
        if reservation is None:
            return None
        if reservation.status != ReservationStatus.ACTIVE:
            return reservation
        status = (
            ReservationStatus.RELEASED
            if reservation.expires_at > now
            else ReservationStatus.EXPIRED
        )
        lock_names = [
            _slot_lock(reservation.slot),
            _alert_lock(reservation.alert_id),
        ]
        if reservation.holder != reservation.alert_id:
            lock_names.append(_holder_lock(reservation.holder))
        for lock in lock_names:
            # Only drop a lock this reservation still owns - after expiry
            # it may already belong to someone else.
            try:
                self._locks.delete_item(
                    Key={"resource": reservation.resource.value, "lock": lock},
                    ConditionExpression="reservation_id = :id",
                    ExpressionAttributeValues={":id": reservation.id},
                )
            except ClientError as exc:
                if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
                    raise
        reservation.status = status
        reservation.released_at = now
        reservation.release_reason = reason
        reservation.detail = {**reservation.detail, **(detail or {})}
        self._reservations.put_item(Item=_to_dynamo(_to_item(reservation)))
        return reservation

    def get(self, reservation_id: str) -> ResourceReservation | None:
        item = self._reservations.get_item(Key={"id": reservation_id}).get("Item")
        return _from_item(item) if item else None

    def list_active(
        self, resource: ReservedResource, now: datetime
    ) -> list[ResourceReservation]:
        now_ts = Decimal(str(now.timestamp()))
        ids = {
            item["reservation_id"]
            for item in self._locks.query(
                KeyConditionExpression=Key("resource").eq(resource.value)
            ).get("Items", [])
            if item["lock"].startswith("slot#") and Decimal(item["expires_at"]) > now_ts
        }
        reservations = [self.get(reservation_id) for reservation_id in ids]
        return [r for r in reservations if r is not None and r.is_active(now)]

    # --- helpers --------------------------------------------------------

    def _put_lock(
        self,
        resource: ReservedResource,
        lock: str,
        reservation: ResourceReservation,
        now_ts: Decimal,
    ) -> dict[str, Any]:
        return {
            "Put": {
                "TableName": LOCKS_TABLE_NAME,
                "Item": {
                    "resource": resource.value,
                    "lock": lock,
                    "reservation_id": reservation.id,
                    "expires_at": Decimal(str(reservation.expires_at.timestamp())),
                },
                "ConditionExpression": _FREE_CONDITION,
                "ExpressionAttributeNames": {"#lock": "lock"},
                "ExpressionAttributeValues": {":now": now_ts},
            }
        }

    def _expire_superseded(
        self,
        previous_locks: list[dict[str, Any] | None],
        new_reservation_id: str,
        now: datetime,
    ) -> None:
        # The locks we just overwrote (if any) belonged to reservations that
        # had expired without being released - record that, best-effort.
        stale_ids = {
            item["reservation_id"]
            for item in previous_locks
            if item is not None and item["reservation_id"] != new_reservation_id
        }
        for reservation_id in stale_ids:
            stale = self.get(reservation_id)
            if stale is None or stale.status != ReservationStatus.ACTIVE:
                continue
            logger.warning(
                "Reservation expired without release: id=%s resource=%s "
                "alert_id=%s holder=%s",
                stale.id,
                stale.resource.value,
                stale.alert_id,
                stale.holder,
            )
            stale.status = ReservationStatus.EXPIRED
            stale.released_at = now
            stale.release_reason = "expired"
            self._reservations.put_item(Item=_to_dynamo(_to_item(stale)))


def _failed_indexes(exc: ClientError) -> set[int]:
    reasons = exc.response.get("CancellationReasons") or []
    return {
        index
        for index, reason in enumerate(reasons)
        if reason.get("Code") == "ConditionalCheckFailed"
    }


def _to_dynamo(value: Any) -> Any:
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: _to_dynamo(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_dynamo(v) for v in value]
    return value


def _from_dynamo(value: Any) -> Any:
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {k: _from_dynamo(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_from_dynamo(v) for v in value]
    return value


def _to_item(reservation: ResourceReservation) -> dict[str, Any]:
    return {
        "id": reservation.id,
        "resource": reservation.resource.value,
        "alert_id": reservation.alert_id,
        "holder": reservation.holder,
        "slot": reservation.slot,
        "reserved_at": reservation.reserved_at.isoformat(),
        "expires_at": reservation.expires_at.isoformat(),
        "status": reservation.status.value,
        "released_at": (
            reservation.released_at.isoformat() if reservation.released_at else None
        ),
        "release_reason": reservation.release_reason,
        "detail": reservation.detail,
    }


def _from_item(item: dict[str, Any]) -> ResourceReservation:
    return ResourceReservation(
        id=item["id"],
        resource=ReservedResource(item["resource"]),
        alert_id=item["alert_id"],
        holder=item["holder"],
        slot=int(item["slot"]),
        reserved_at=datetime.fromisoformat(item["reserved_at"]),
        expires_at=datetime.fromisoformat(item["expires_at"]),
        status=ReservationStatus(item["status"]),
        released_at=(
            datetime.fromisoformat(item["released_at"])
            if item.get("released_at")
            else None
        ),
        release_reason=item.get("release_reason"),
        detail=_from_dynamo(item.get("detail") or {}),
    )
