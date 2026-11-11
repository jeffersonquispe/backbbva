"""Cold fraud-history archive lookup and legal holds (#11c).

The HTTP audit only records the route template, so the use cases write their
own audit entries (who read or held which alert_id) on top of the audited
DynamoDB client's record of each hold write.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from src.application.ports.fraud_history_archive_port import ArchiveVerificationError
from src.application.ports.local_auth_port import LocalUser
from src.application.use_cases.fraud_review.get_archived_alert import (
    ArchivedAlertNotFoundError,
    GetArchivedAlert,
)
from src.application.use_cases.fraud_review.manage_legal_hold import (
    GetLegalHold,
    LegalHoldAlertNotFoundError,
    LegalHoldAlreadyActiveError,
    LegalHoldNotActiveError,
    LegalHoldNotFoundError,
    LegalHoldReasonError,
    ListLegalHolds,
    PlaceLegalHold,
    ReleaseLegalHold,
)
from src.application.use_cases.fraud_review.search_archived_alerts import (
    ArchiveSearchCriteriaError,
    SearchArchivedAlerts,
)
from src.infrastructure.entrypoint.api.authorization import require_permission
from src.infrastructure.entrypoint.api.factories.fraud_archive_factory import (
    get_get_archived_alert_use_case,
    get_get_legal_hold_use_case,
    get_list_legal_holds_use_case,
    get_place_legal_hold_use_case,
    get_release_legal_hold_use_case,
    get_search_archived_alerts_use_case,
)

router = APIRouter(prefix="/fraud-history", tags=["fraud-history"])


class ArchivedAlertResponse(BaseModel):
    alert_id: str
    created_day: date
    archive_object: str
    verified_against: str
    alert: dict[str, Any]
    fraud_label_reviews: list[dict[str, Any]]


class ArchivedAlertHitResponse(BaseModel):
    alert_id: str
    event_id: str | None = None
    created_day: date
    legal_hold: bool


class PlaceLegalHoldRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=2_000)
    case_reference: str | None = Field(default=None, max_length=200)


class ReleaseLegalHoldRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=2_000)


class LegalHoldResponse(BaseModel):
    alert_id: str
    active: bool
    reason: str
    case_reference: str | None = None
    placed_by: str
    placed_at: datetime
    released_at: datetime | None = None
    released_by: str | None = None
    release_reason: str | None = None


def _hold_response(hold) -> LegalHoldResponse:
    return LegalHoldResponse(
        alert_id=hold.alert_id,
        active=hold.active,
        reason=hold.reason,
        case_reference=hold.case_reference,
        placed_by=hold.placed_by,
        placed_at=hold.placed_at,
        released_at=hold.released_at,
        released_by=hold.released_by,
        release_reason=hold.release_reason,
    )


@router.get("/archive", response_model=list[ArchivedAlertHitResponse])
def search_archived_alerts(
    user: Annotated[LocalUser, Depends(require_permission("fraud_archive"))],
    use_case: Annotated[
        SearchArchivedAlerts, Depends(get_search_archived_alerts_use_case)
    ],
    alert_id: Annotated[str | None, Query(max_length=128)] = None,
    event_id: Annotated[str | None, Query(max_length=256)] = None,
    day: Annotated[date | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[ArchivedAlertHitResponse]:
    """Archived alerts by alert id, event id or creation day (exactly one)."""
    try:
        hits = use_case.execute(
            requested_by=str(user.id),
            alert_id=alert_id,
            event_id=event_id,
            day=day,
            limit=limit,
        )
    except ArchiveSearchCriteriaError as error:
        raise HTTPException(
            status_code=422, detail={"code": "ARCHIVE_SEARCH_CRITERIA"}
        ) from error
    return [
        ArchivedAlertHitResponse(
            alert_id=hit.summary.alert_id,
            event_id=hit.summary.event_id,
            created_day=hit.summary.created_day,
            legal_hold=hit.legal_hold,
        )
        for hit in hits
    ]


@router.get("/archive/{alert_id}", response_model=ArchivedAlertResponse)
def get_archived_alert(
    alert_id: str,
    user: Annotated[LocalUser, Depends(require_permission("fraud_archive"))],
    use_case: Annotated[GetArchivedAlert, Depends(get_get_archived_alert_use_case)],
) -> ArchivedAlertResponse:
    """An alert older than the hot window, read back from cold storage."""
    try:
        archived = use_case.execute(alert_id, requested_by=str(user.id)).archived
    except ArchivedAlertNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "ARCHIVED_ALERT_NOT_FOUND"},
        ) from error
    except ArchiveVerificationError as error:
        # The stored bytes no longer match their digest: never serve them.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "ARCHIVE_INTEGRITY_FAILED"},
        ) from error
    return ArchivedAlertResponse(
        alert_id=archived.alert_id,
        created_day=archived.created_day,
        archive_object=archived.object_key,
        verified_against=archived.verified_against,
        alert=archived.alert,
        fraud_label_reviews=archived.fraud_label_reviews,
    )


@router.get(
    "/legal-holds",
    response_model=list[LegalHoldResponse],
    dependencies=[Depends(require_permission("legal_hold"))],
)
def list_legal_holds(
    use_case: Annotated[ListLegalHolds, Depends(get_list_legal_holds_use_case)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[LegalHoldResponse]:
    """Alerts currently under legal hold, newest first."""
    return [_hold_response(hold) for hold in use_case.execute(limit=limit)]


@router.get(
    "/legal-holds/{alert_id}",
    response_model=LegalHoldResponse,
    dependencies=[Depends(require_permission("fraud_archive"))],
)
def get_legal_hold(
    alert_id: str,
    use_case: Annotated[GetLegalHold, Depends(get_get_legal_hold_use_case)],
) -> LegalHoldResponse:
    """The hold of one alert (active or released), for its detail view."""
    try:
        return _hold_response(use_case.execute(alert_id))
    except LegalHoldNotFoundError as error:
        raise HTTPException(
            status_code=404, detail={"code": "LEGAL_HOLD_NOT_FOUND"}
        ) from error


@router.put(
    "/legal-holds/{alert_id}",
    response_model=LegalHoldResponse,
    status_code=status.HTTP_201_CREATED,
)
def place_legal_hold(
    alert_id: str,
    request: PlaceLegalHoldRequest,
    user: Annotated[LocalUser, Depends(require_permission("legal_hold"))],
    use_case: Annotated[PlaceLegalHold, Depends(get_place_legal_hold_use_case)],
) -> LegalHoldResponse:
    try:
        hold = use_case.execute(
            alert_id=alert_id,
            reason=request.reason,
            case_reference=request.case_reference,
            placed_by=str(user.id),
        )
    except LegalHoldReasonError as error:
        raise HTTPException(
            status_code=422, detail={"code": "LEGAL_HOLD_REASON", "message": str(error)}
        ) from error
    except LegalHoldAlertNotFoundError as error:
        raise HTTPException(
            status_code=404, detail={"code": "ALERT_NOT_FOUND"}
        ) from error
    except LegalHoldAlreadyActiveError as error:
        raise HTTPException(
            status_code=409, detail={"code": "LEGAL_HOLD_ALREADY_ACTIVE"}
        ) from error
    return _hold_response(hold)


@router.post(
    "/legal-holds/{alert_id}/release",
    response_model=LegalHoldResponse,
)
def release_legal_hold(
    alert_id: str,
    request: ReleaseLegalHoldRequest,
    user: Annotated[LocalUser, Depends(require_permission("legal_hold"))],
    use_case: Annotated[ReleaseLegalHold, Depends(get_release_legal_hold_use_case)],
) -> LegalHoldResponse:
    try:
        hold = use_case.execute(
            alert_id=alert_id, reason=request.reason, released_by=str(user.id)
        )
    except LegalHoldReasonError as error:
        raise HTTPException(
            status_code=422, detail={"code": "LEGAL_HOLD_REASON", "message": str(error)}
        ) from error
    except LegalHoldNotActiveError as error:
        raise HTTPException(
            status_code=404, detail={"code": "LEGAL_HOLD_NOT_ACTIVE"}
        ) from error
    return _hold_response(hold)
