from __future__ import annotations

from dataclasses import fields
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.application.dtos.async_operation_dtos import CreateAsyncOperationInput
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
from src.application.use_cases.async_operations.create_async_operation import (
    CreateAsyncOperationUseCase,
)
from src.application.use_cases.datasets.configure_mature_sampler_schema import (
    GetMatureSamplerSchemaConfigurationUseCase,
    UpdateMatureSamplerSchemaConfigurationUseCase,
)
from src.application.use_cases.datasets.preview_mature_sample import (
    PreviewMatureSampleUseCase,
)
from src.domain.datasets.mature_sample_entities import MatureSamplerSchemaMapping
from src.infrastructure.entrypoint.api.factories.assistant_optimizer_settings_factory import (
    get_get_assistant_optimizer_settings_use_case,
    get_list_assistant_optimizer_settings_changes_use_case,
    get_mature_sampler_schema_configuration_use_case,
    get_preview_mature_sample_use_case,
    get_start_mature_sample_use_case,
    get_update_assistant_optimizer_settings_use_case,
    get_update_mature_sampler_schema_configuration_use_case,
)
from src.infrastructure.entrypoint.api.routers.auth_router import get_current_user
from src.infrastructure.entrypoint.api.schemas.assistant_optimizer_settings import (
    AssistantOptimizerSettingsChangeResponse,
    AssistantOptimizerSettingsRequest,
    AssistantOptimizerSettingsSchema,
    MatureSamplePreviewResponse,
    MatureSamplerSchemaConfigurationResponse,
    MatureSamplerSchemaMappingRequest,
)
from src.infrastructure.entrypoint.api.schemas.async_operations import (
    AsyncOperationResponse,
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
    field_pool: Annotated[
        PreviewMatureSampleUseCase,
        Depends(get_preview_mature_sample_use_case),
    ],
):
    _require_editor(user)
    proposed = AssistantOptimizerSettings(**request.settings.model_dump())
    try:
        field_pool.validate_selected_fields(
            proposed.sampler_strata,
            proposed.sampler_compatible_schema_versions,
        )
        settings = use_case.execute(proposed, changed_by=user.email)
    except (ValidationError, ValueError) as exc:
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


@router.post("/sampler/preview", response_model=MatureSamplePreviewResponse)
def preview_mature_sample(
    use_case: Annotated[
        PreviewMatureSampleUseCase,
        Depends(get_preview_mature_sample_use_case),
    ],
    user: Annotated[LocalUser, Depends(get_current_user)],
):
    _require_editor(user)
    try:
        result = use_case.execute()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return result


@router.get("/sampler/fields", response_model=list[str])
def list_sampler_fields(
    use_case: Annotated[
        PreviewMatureSampleUseCase,
        Depends(get_preview_mature_sample_use_case),
    ],
    user: Annotated[LocalUser, Depends(get_current_user)],
) -> list[str]:
    _require_editor(user)
    return use_case.available_fields()


@router.get(
    "/sampler/schema-configuration",
    response_model=MatureSamplerSchemaConfigurationResponse,
)
def get_sampler_schema_configuration(
    use_case: Annotated[
        GetMatureSamplerSchemaConfigurationUseCase,
        Depends(get_mature_sampler_schema_configuration_use_case),
    ],
    user: Annotated[LocalUser, Depends(get_current_user)],
):
    _require_editor(user)
    return use_case.execute()


@router.put(
    "/sampler/schema-configuration",
    response_model=MatureSamplerSchemaConfigurationResponse,
)
def update_sampler_schema_configuration(
    request: MatureSamplerSchemaMappingRequest,
    use_case: Annotated[
        UpdateMatureSamplerSchemaConfigurationUseCase,
        Depends(get_update_mature_sampler_schema_configuration_use_case),
    ],
    reader: Annotated[
        GetMatureSamplerSchemaConfigurationUseCase,
        Depends(get_mature_sampler_schema_configuration_use_case),
    ],
    user: Annotated[LocalUser, Depends(get_current_user)],
):
    _require_editor(user)
    try:
        use_case.execute(
            MatureSamplerSchemaMapping(
                target_field=request.target_field,
                marking_date_field=request.marking_date_field,
                label_value_mapping=request.label_value_mapping,
            ),
            changed_by=user.email,
        )
        return reader.execute()
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/sampler/run",
    response_model=AsyncOperationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_mature_sample(
    use_case: Annotated[
        CreateAsyncOperationUseCase,
        Depends(get_start_mature_sample_use_case),
    ],
    user: Annotated[LocalUser, Depends(get_current_user)],
):
    _require_editor(user)
    return use_case.execute(
        CreateAsyncOperationInput(
            operation_type="mature_sample.create",
            payload={"trigger": "manual"},
            created_by=user.email,
        )
    )
