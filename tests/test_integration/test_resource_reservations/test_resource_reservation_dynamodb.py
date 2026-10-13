"""Docker-only integration tests against the real DynamoDB Local service -
TransactWriteItems + conditional puts are exactly what an in-memory fake
can't prove."""
from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest

if not os.getenv("DYNAMO_ENDPOINT"):
    pytest.skip("Requires DynamoDB Local (set DYNAMO_ENDPOINT)", allow_module_level=True)

from src.application.ports.resource_reservation_port import (
    ReservationConflict,
    ReservationStatus,
    ReservedResource,
)
from src.infrastructure.persistence.database.dynamodb.manager import create_table
from src.infrastructure.persistence.database.dynamodb.repositories.resource_reservation_repository import (
    DynamoResourceReservationRepository,
)
from src.infrastructure.persistence.database.dynamodb.schemas import (
    RESOURCE_LOCKS_TABLE,
    RESOURCE_RESERVATIONS_TABLE,
)

pytestmark = pytest.mark.docker_integration

NOW = datetime.now(UTC)


@pytest.fixture(scope="module")
def repo() -> DynamoResourceReservationRepository:
    create_table(RESOURCE_LOCKS_TABLE)
    create_table(RESOURCE_RESERVATIONS_TABLE)
    return DynamoResourceReservationRepository()


def _ids() -> tuple[str, str, str]:
    # Unique per test: the tables are shared with the running stack, and
    # the analyst pool is global - unique holders/alerts keep tests apart.
    return str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())


def _free_all(repo, resource: ReservedResource) -> None:
    for reservation in repo.list_active(resource, NOW):
        repo.release(reservation.id, reason="test_cleanup", now=NOW)


def test_quota_holder_and_alert_locks_are_enforced(repo) -> None:
    _free_all(repo, ReservedResource.ANALYST)
    alert_a, alert_b, alert_c = _ids()
    analyst_1, analyst_2, analyst_3 = _ids()

    first = repo.try_acquire(
        ReservedResource.ANALYST, alert_id=alert_a, holder=analyst_1, capacity=2, now=NOW
    )
    assert first.reservation is not None

    same_alert = repo.try_acquire(
        ReservedResource.ANALYST, alert_id=alert_a, holder=analyst_2, capacity=2, now=NOW
    )
    assert same_alert.conflict == ReservationConflict.ALERT_TAKEN

    busy = repo.try_acquire(
        ReservedResource.ANALYST, alert_id=alert_b, holder=analyst_1, capacity=2, now=NOW
    )
    assert busy.conflict == ReservationConflict.HOLDER_BUSY

    second = repo.try_acquire(
        ReservedResource.ANALYST, alert_id=alert_b, holder=analyst_2, capacity=2, now=NOW
    )
    assert second.reservation is not None
    assert {first.reservation.slot, second.reservation.slot} == {0, 1}

    full = repo.try_acquire(
        ReservedResource.ANALYST, alert_id=alert_c, holder=analyst_3, capacity=2, now=NOW
    )
    assert full.conflict == ReservationConflict.NO_CAPACITY

    released = repo.release(first.reservation.id, reason="resolved", now=NOW, detail={"decision": "pass"})
    assert released.status == ReservationStatus.RELEASED
    assert released.detail == {"decision": "pass"}

    after = repo.try_acquire(
        ReservedResource.ANALYST, alert_id=alert_c, holder=analyst_3, capacity=2, now=NOW
    )
    assert after.reservation is not None
    assert after.reservation.slot == first.reservation.slot
    _free_all(repo, ReservedResource.ANALYST)


def test_expired_reservation_frees_its_slot_and_is_marked_expired(repo) -> None:
    _free_all(repo, ReservedResource.VOICEBOT)
    old_alert, new_alert, _ = _ids()
    stale = repo.try_acquire(
        ReservedResource.VOICEBOT,
        alert_id=old_alert,
        holder=old_alert,
        capacity=1,
        now=NOW - timedelta(minutes=40),
    ).reservation
    assert stale is not None
    assert repo.list_active(ReservedResource.VOICEBOT, NOW) == []

    fresh = repo.try_acquire(
        ReservedResource.VOICEBOT, alert_id=new_alert, holder=new_alert, capacity=1, now=NOW
    ).reservation

    assert fresh is not None and fresh.slot == stale.slot
    assert repo.get(stale.id).status == ReservationStatus.EXPIRED
    assert [r.id for r in repo.list_active(ReservedResource.VOICEBOT, NOW)] == [fresh.id]
    # Releasing the stale one must not drop the fresh holder's lock.
    repo.release(stale.id, reason="late_callback", now=NOW)
    assert [r.id for r in repo.list_active(ReservedResource.VOICEBOT, NOW)] == [fresh.id]
    _free_all(repo, ReservedResource.VOICEBOT)
