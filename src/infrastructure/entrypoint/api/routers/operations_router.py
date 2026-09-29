from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status

from src.application.ports.local_auth_port import LocalUser
from src.application.use_cases.operations.complete_voicebot_call import (
    CompleteVoicebotCallUseCase,
)
from src.application.use_cases.operations.live_operations_capacity import (
    LiveOperationsCapacity,
)
from src.domain.alerts.exceptions import NoActiveVoicebotCallError
from src.infrastructure.core.config import genai_config
from src.infrastructure.entrypoint.api.factories.operations_factory import (
    get_complete_voicebot_call_use_case,
    get_live_operations_capacity,
)
from src.infrastructure.entrypoint.api.routers.auth_router import get_current_user
from src.infrastructure.entrypoint.api.schemas import (
    ChannelCapacitySchema,
    OperationsCapacityResponse,
    VoicebotCallbackRequest,
)

router = APIRouter(tags=["operations"])


@router.get("/operations/capacity", response_model=OperationsCapacityResponse)
def get_operations_capacity(
    _: Annotated[LocalUser, Depends(get_current_user)],
    capacity: Annotated[LiveOperationsCapacity, Depends(get_live_operations_capacity)],
):
    record = capacity.get_capacity()
    return OperationsCapacityResponse(
        analysts=ChannelCapacitySchema(**record.analysts.__dict__),
        voicebot=ChannelCapacitySchema(**record.voicebot.__dict__),
        bidi=ChannelCapacitySchema(**record.bidi.__dict__),
        updated_at=record.updated_at,
    )


def _check_voicebot_token(authorization: str | None) -> None:
    # Opt-in shared secret (VOICEBOT_CALLBACK_TOKEN) - unset locally.
    expected = genai_config.VOICEBOT_CALLBACK_TOKEN
    if not expected:
        return
    if not authorization or not hmac.compare_digest(
        authorization, f"Bearer {expected}"
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)


@router.post("/voicebot/callbacks", status_code=status.HTTP_204_NO_CONTENT)
def voicebot_callback(
    request: VoicebotCallbackRequest,
    use_case: Annotated[
        CompleteVoicebotCallUseCase, Depends(get_complete_voicebot_call_use_case)
    ],
    authorization: Annotated[str | None, Header()] = None,
):
    """Called by the voicebot provider when a call ends: frees the slot."""
    _check_voicebot_token(authorization)
    try:
        use_case.execute(str(request.alert_id), request.outcome, request.detail)
    except NoActiveVoicebotCallError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
