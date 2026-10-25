from __future__ import annotations

import json
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from jwt import PyJWKClientConnectionError
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.application.ports.event_publisher_port import (
    EventIdConflictError,
    EventPublisherPort,
)
from src.application.use_cases.event_api.receive_alert_event import (
    ReceiveAlertEventUseCase,
)
from src.infrastructure.entrypoint.event_api.oidc import (
    OidcTokenVerifier,
    get_oidc_verifier,
)
from src.infrastructure.entrypoint.event_api.settings import event_api_settings
from src.infrastructure.queues.celery.event_api_publisher import get_event_publisher


class AlertEventRequest(BaseModel):
    # FRM may send additional summary attributes; the intake contract deliberately
    # consumes only the two identifiers and leaves enrichment to the production
    # pre-process step.
    model_config = ConfigDict(extra="ignore")

    alert_id: str = Field(min_length=1, max_length=256, pattern=r"^\S+$")
    event_id: str = Field(min_length=1, max_length=256, pattern=r"^\S+$")


class AlertEventResponse(BaseModel):
    receipt_id: str
    status: str = "accepted"
    duplicate: bool


app = FastAPI(title="ARIA Event API", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post(
    "/api/event/events",
    response_model=AlertEventResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def receive_event(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    verifier: OidcTokenVerifier = Depends(get_oidc_verifier),
    publisher: EventPublisherPort = Depends(get_event_publisher),
) -> AlertEventResponse:
    settings = event_api_settings()
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Bearer token required")
    token = authorization.removeprefix("Bearer ").strip()
    try:
        verifier.verify(token)
    except PyJWKClientConnectionError as exc:
        raise HTTPException(status_code=503, detail="OIDC issuer unavailable") from exc
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid OIDC token") from exc

    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > settings.max_body_bytes:
                raise HTTPException(status_code=413, detail="Request body too large")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid content length") from exc
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > settings.max_body_bytes:
            raise HTTPException(status_code=413, detail="Request body too large")
        body.extend(chunk)
    try:
        data = json.loads(bytes(body))
        payload = AlertEventRequest.model_validate(data)
    except (json.JSONDecodeError, UnicodeDecodeError, ValidationError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid event JSON") from exc
    try:
        receipt = ReceiveAlertEventUseCase(publisher).execute(
            payload.alert_id, payload.event_id
        )
    except EventIdConflictError as exc:
        raise HTTPException(status_code=409, detail="event_id already belongs to another alert") from exc
    except Exception as exc:
        raise HTTPException(
            status_code=503, detail="Production queue unavailable; retry the event"
        ) from exc
    return AlertEventResponse(
        receipt_id=receipt.receipt_id, duplicate=receipt.duplicate
    )
