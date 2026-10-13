from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from src.application.dtos.analyst_queue_dtos import (
    AlertDetail,
    AnalystQueueItem,
    ResolveEscalatedAlertInput,
)
from src.application.ports.local_auth_port import LocalRole, LocalUser
from src.application.ports.resource_reservation_port import ResourceReservation
from src.application.use_cases.analyst_queue.get_alert_detail import (
    GetAlertDetailUseCase,
)
from src.application.use_cases.analyst_queue.list_analyst_queue import (
    ListAnalystQueueUseCase,
)
from src.application.use_cases.analyst_queue.release_escalated_alert import (
    ReleaseEscalatedAlertUseCase,
)
from src.application.use_cases.analyst_queue.resolve_escalated_alert import (
    ResolveEscalatedAlertUseCase,
)
from src.application.use_cases.analyst_queue.take_escalated_alert import (
    TakeEscalatedAlertUseCase,
)
from src.application.use_cases.auth.local_auth import GetCurrentLocalUserUseCase
from src.domain.alerts.exceptions import (
    AlertAlreadyTakenError,
    AlertNotFoundError,
    AlertNotHeldByAnalystError,
    AlertNotInAnalystQueueError,
    AnalystBusyError,
    NoAnalystCapacityError,
)
from src.infrastructure.entrypoint.api.factories.local_auth_factory import (
    get_current_local_user_use_case,
)
from src.infrastructure.entrypoint.api.factories.operations_factory import (
    get_alert_detail_use_case,
    get_list_analyst_queue_use_case,
    get_release_escalated_alert_use_case,
    get_resolve_escalated_alert_use_case,
    get_take_escalated_alert_use_case,
)
from src.infrastructure.entrypoint.api.routers.auth_router import get_current_user
from src.infrastructure.entrypoint.api.schemas import (
    AlertDetailResponse,
    AlertStepResponse,
    AnalystQueueAlertResponse,
    ResolveEscalatedAlertRequest,
    ResourceReservationResponse,
)

router = APIRouter(prefix="/analyst-queue", tags=["analyst-queue"])

CurrentUser = Annotated[LocalUser, Depends(get_current_user)]
UserLookup = Annotated[
    GetCurrentLocalUserUseCase, Depends(get_current_local_user_use_case)
]


def _require_fraud_analyst(user: LocalUser) -> None:
    # Only human fraud analysts take and resolve alerts; every other role
    # with /cola access sees the queue read-only.
    if user.role != LocalRole.FRAUD_ANALYST:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only fraud analysts can take or resolve escalated alerts.",
        )


@router.get("", response_model=list[AnalystQueueAlertResponse])
def list_analyst_queue(
    _: CurrentUser,
    users: UserLookup,
    use_case: Annotated[
        ListAnalystQueueUseCase, Depends(get_list_analyst_queue_use_case)
    ],
):
    return [_queue_item_response(item, users) for item in use_case.execute()]


@router.get("/{alert_id}", response_model=AlertDetailResponse)
def get_alert_detail(
    alert_id: UUID,
    _: CurrentUser,
    users: UserLookup,
    use_case: Annotated[GetAlertDetailUseCase, Depends(get_alert_detail_use_case)],
):
    try:
        detail = use_case.execute(alert_id)
    except AlertNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _detail_response(detail, users)


@router.post("/{alert_id}/take", response_model=ResourceReservationResponse)
def take_alert(
    alert_id: UUID,
    user: CurrentUser,
    users: UserLookup,
    use_case: Annotated[
        TakeEscalatedAlertUseCase, Depends(get_take_escalated_alert_use_case)
    ],
):
    _require_fraud_analyst(user)
    try:
        reservation = use_case.execute(alert_id, str(user.id))
    except AlertNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (
        AlertNotInAnalystQueueError,
        AnalystBusyError,
        AlertAlreadyTakenError,
        NoAnalystCapacityError,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": _conflict_code(exc), "message": str(exc)},
        ) from exc
    return _reservation_response(reservation, users)


@router.post("/{alert_id}/resolve", response_model=ResourceReservationResponse)
def resolve_alert(
    alert_id: UUID,
    request: ResolveEscalatedAlertRequest,
    user: CurrentUser,
    users: UserLookup,
    use_case: Annotated[
        ResolveEscalatedAlertUseCase, Depends(get_resolve_escalated_alert_use_case)
    ],
):
    _require_fraud_analyst(user)
    try:
        reservation = use_case.execute(
            ResolveEscalatedAlertInput(
                alert_id=str(alert_id),
                analyst_id=str(user.id),
                decision=request.decision,
                notes=request.notes,
            )
        )
    except AlertNotHeldByAnalystError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "not_held", "message": str(exc)},
        ) from exc
    return _reservation_response(reservation, users)


@router.post("/{alert_id}/release", response_model=ResourceReservationResponse)
def release_alert(
    alert_id: UUID,
    user: CurrentUser,
    users: UserLookup,
    use_case: Annotated[
        ReleaseEscalatedAlertUseCase, Depends(get_release_escalated_alert_use_case)
    ],
):
    _require_fraud_analyst(user)
    try:
        reservation = use_case.execute(str(alert_id), str(user.id))
    except AlertNotHeldByAnalystError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "not_held", "message": str(exc)},
        ) from exc
    return _reservation_response(reservation, users)


def _conflict_code(exc: Exception) -> str:
    return {
        AlertNotInAnalystQueueError: "not_in_queue",
        AnalystBusyError: "analyst_busy",
        AlertAlreadyTakenError: "alert_taken",
        NoAnalystCapacityError: "no_capacity",
    }[type(exc)]


def _holder_name(
    reservation: ResourceReservation, users: GetCurrentLocalUserUseCase
) -> str | None:
    try:
        user = users.execute(UUID(reservation.holder))
    except ValueError:
        return None
    return user.name if user is not None else None


def _reservation_response(
    reservation: ResourceReservation, users: GetCurrentLocalUserUseCase
) -> ResourceReservationResponse:
    return ResourceReservationResponse(
        id=reservation.id,
        resource=reservation.resource.value,
        alert_id=reservation.alert_id,
        holder=reservation.holder,
        holder_name=_holder_name(reservation, users),
        reserved_at=reservation.reserved_at,
        expires_at=reservation.expires_at,
        status=reservation.status.value,
        released_at=reservation.released_at,
        release_reason=reservation.release_reason,
        detail=reservation.detail,
    )


def _queue_item_response(
    item: AnalystQueueItem, users: GetCurrentLocalUserUseCase
) -> AnalystQueueAlertResponse:
    alert = item.alert
    return AnalystQueueAlertResponse(
        alert_id=alert.id,
        event_id=alert.event_id,
        event_type=alert.event_type,
        status=alert.status.value,
        customer_id=alert.customer_id,
        created_at=alert.created_at,
        schema_version=alert.schema_version,
        configuration_ref=(
            {
                "configuration_id": alert.configuration_id,
                "version": alert.configuration_version,
            }
            if alert.configuration_id is not None
            else None
        ),
        input=alert.input,
        labels=alert.labels,
        history_prev_alerta=alert.history_prev_alerta,
        agent_output=alert.agent_output,
        reservation=(
            _reservation_response(item.reservation, users)
            if item.reservation is not None
            else None
        ),
    )


def _detail_response(
    detail: AlertDetail, users: GetCurrentLocalUserUseCase
) -> AlertDetailResponse:
    base = _queue_item_response(
        AnalystQueueItem(alert=detail.alert, reservation=detail.reservation), users
    )
    workflow = detail.workflow
    return AlertDetailResponse(
        **base.model_dump(),
        workflow_execution_id=workflow.id if workflow else None,
        workflow_status=workflow.status.value if workflow else None,
        workflow_output=workflow.output if workflow else None,
        steps=[
            AlertStepResponse(
                step_name=step.step_name,
                status=step.status.value,
                attempt=step.attempt,
                output=step.output,
                error=step.error,
                started_at=step.started_at,
                finished_at=step.finished_at,
            )
            for step in detail.steps
        ],
    )
