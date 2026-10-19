from __future__ import annotations

from dataclasses import fields
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.application.errors import ValidationError
from src.application.ports.assistant_optimizer_settings_port import (
    AssistantOptimizerSettings,
)
from src.application.ports.local_auth_port import LocalRole, LocalUser
from src.application.use_cases.assistant_optimizer_settings import (
    GetAssistantOptimizerSettingsUseCase,
    ListAssistantOptimizerSettingsChangesUseCase,
    UpdateAssistantOptimizerSettingsUseCase,
)
from src.infrastructure.entrypoint.api.factories.assistant_optimizer_settings_factory import (
    get_get_assistant_optimizer_settings_use_case,
    get_list_assistant_optimizer_settings_changes_use_case,
    get_update_assistant_optimizer_settings_use_case,
)
from src.infrastructure.entrypoint.api.routers.auth_router import get_current_user
from src.infrastructure.entrypoint.api.schemas.assistant_optimizer_settings import (
    AssistantOptimizerSettingsChangeResponse,
    AssistantOptimizerSettingsRequest,
    AssistantOptimizerSettingsSchema,
)

router = APIRouter(
    prefix="/assistant-optimizer-settings", tags=["assistant-optimizer-settings"]
)
_NON_PERSISTED_FIELDS = {"maturing_days", "expected_coverage_pct", "stable_months"}


def _require_editor(user: LocalUser) -> None:
    if user.role not in (LocalRole.RELEASE_MANAGER, LocalRole.MANAGER):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Role is not permitted to manage assistant optimizer settings",
        )


@router.get("", response_model=AssistantOptimizerSettingsSchema)
def get_settings(
    use_case: Annotated[
        GetAssistantOptimizerSettingsUseCase,
        Depends(get_get_assistant_optimizer_settings_use_case),
    ],
    user: Annotated[LocalUser, Depends(get_current_user)],
):
    _require_editor(user)
    settings = use_case.execute()
    return {
        field.name: getattr(settings, field.name)
        for field in fields(settings)
        if field.name not in _NON_PERSISTED_FIELDS
    }


@router.put("", response_model=AssistantOptimizerSettingsSchema)
def update_settings(
    request: AssistantOptimizerSettingsRequest,
    use_case: Annotated[
        UpdateAssistantOptimizerSettingsUseCase,
        Depends(get_update_assistant_optimizer_settings_use_case),
    ],
    user: Annotated[LocalUser, Depends(get_current_user)],
):
    _require_editor(user)
    proposed = AssistantOptimizerSettings(**request.settings.model_dump())
    try:
        settings = use_case.execute(proposed, changed_by=user.email)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        field.name: getattr(settings, field.name)
        for field in fields(settings)
        if field.name not in _NON_PERSISTED_FIELDS
    }


@router.get(
    "/changes", response_model=list[AssistantOptimizerSettingsChangeResponse]
)
def list_changes(
    use_case: Annotated[
        ListAssistantOptimizerSettingsChangesUseCase,
        Depends(get_list_assistant_optimizer_settings_changes_use_case),
    ],
    user: Annotated[LocalUser, Depends(get_current_user)],
    limit: int = Query(default=50, ge=1, le=100),
):
    _require_editor(user)
    return use_case.execute(limit)
