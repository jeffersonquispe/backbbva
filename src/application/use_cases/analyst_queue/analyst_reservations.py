from __future__ import annotations

from datetime import datetime

from src.application.ports.resource_reservation_port import (
    ReservedResource,
    ResourceReservation,
    ResourceReservationRepository,
)


def active_reservation_for_alert(
    reservations: ResourceReservationRepository,
    resource: ReservedResource,
    alert_id: str,
    now: datetime,
) -> ResourceReservation | None:
    return next(
        (
            reservation
            for reservation in reservations.list_active(resource, now)
            if reservation.alert_id == alert_id
        ),
        None,
    )


def active_reservation_for_holder(
    reservations: ResourceReservationRepository,
    resource: ReservedResource,
    holder: str,
    now: datetime,
) -> ResourceReservation | None:
    return next(
        (
            reservation
            for reservation in reservations.list_active(resource, now)
            if reservation.holder == holder
        ),
        None,
    )
