from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from src.application.dtos.operational_settings_dtos import (
    UpdateOperationalSettingsInput,
)
from src.application.ports.configuration_port import (
    AnalystCapacity,
    DayProfile,
    ShortageBehavior,
)
from src.application.ports.operational_settings_port import (
    OperationalSettings,
    OperationalSettingsChange,
)
from src.application.use_cases.operational_settings.get_operational_settings import (
    GetOperationalSettingsUseCase,
)
from src.application.use_cases.operational_settings.list_operational_settings_history import (
    ListOperationalSettingsHistoryUseCase,
)
from src.application.use_cases.operational_settings.update_operational_settings import (
    UpdateOperationalSettingsUseCase,
)
from src.infrastructure.entrypoint.api.factories.operational_settings_factory import (
    get_get_operational_settings_use_case,
    get_list_operational_settings_history_use_case,
    get_update_operational_settings_use_case,
)
from src.infrastructure.entrypoint.api.schemas import (
    AnalystCapacitySchema,
    DayProfileSchema,
    OperationalSettingsChangeResponse,
    OperationalSettingsSchema,
    SettingChangeResponse,
    ShortageBehaviorSchema,
    UpdateOperationalSettingsRequest,
)

# No permission Depends here - intentional, not an oversight: this codebase
# has no auth/permission system wired anywhere yet (see AUDIT_FINDINGS.md;
# OrganizationRole.ADMIN in auth_port.py is defined but unused). changed_by
# below is captured as free text for traceability only, not a verified
# identity.
router = APIRouter(prefix="/operational-settings", tags=["operational-settings"])


@router.get("", response_model=OperationalSettingsSchema)
def get_operational_settings(
    use_case: Annotated[
        GetOperationalSettingsUseCase, Depends(get_get_operational_settings_use_case)
    ],
):
    return _to_schema(use_case.execute())


@router.put("", response_model=OperationalSettingsSchema)
def update_operational_settings(
    request: UpdateOperationalSettingsRequest,
    use_case: Annotated[
        UpdateOperationalSettingsUseCase,
        Depends(get_update_operational_settings_use_case),
    ],
):
    updated = use_case.execute(
        UpdateOperationalSettingsInput(
            settings=_from_schema(request.settings),
            changed_by=request.changed_by,
        )
    )
    return _to_schema(updated)


@router.get("/history", response_model=list[OperationalSettingsChangeResponse])
def list_operational_settings_history(
    use_case: Annotated[
        ListOperationalSettingsHistoryUseCase,
        Depends(get_list_operational_settings_history_use_case),
    ],
    limit: int = 50,
):
    return [_change_to_response(change) for change in use_case.execute(limit)]


def _to_schema(settings: OperationalSettings) -> OperationalSettingsSchema:
    return OperationalSettingsSchema(
        agent_enabled=settings.agent_enabled,
        analyst_escalation_enabled=settings.analyst_escalation_enabled,
        voicebot_escalation_enabled=settings.voicebot_escalation_enabled,
        max_instances=settings.max_instances,
        auto_scale=settings.auto_scale,
        voicebot_max_concurrent_calls=settings.voicebot_max_concurrent_calls,
        voicebot_shortage_behavior=ShortageBehaviorSchema(
            **settings.voicebot_shortage_behavior.__dict__
        ),
        analyst_capacity=AnalystCapacitySchema(
            profiles=[
                DayProfileSchema(**p.__dict__)
                for p in settings.analyst_capacity.profiles
            ],
            default_profile_id=settings.analyst_capacity.default_profile_id,
            day_overrides=settings.analyst_capacity.day_overrides,
        ),
        analyst_shortage_behavior=ShortageBehaviorSchema(
            **settings.analyst_shortage_behavior.__dict__
        ),
        max_test_instances=settings.max_test_instances,
        max_concurrent_experiments=settings.max_concurrent_experiments,
        experiment_timeout_minutes=settings.experiment_timeout_minutes,
        max_stored_test_runs=settings.max_stored_test_runs,
        test_cleanup_policy=settings.test_cleanup_policy,
    )


def _from_schema(schema: OperationalSettingsSchema) -> OperationalSettings:
    return OperationalSettings(
        agent_enabled=schema.agent_enabled,
        analyst_escalation_enabled=schema.analyst_escalation_enabled,
        voicebot_escalation_enabled=schema.voicebot_escalation_enabled,
        max_instances=schema.max_instances,
        auto_scale=schema.auto_scale,
        voicebot_max_concurrent_calls=schema.voicebot_max_concurrent_calls,
        voicebot_shortage_behavior=ShortageBehavior(
            **schema.voicebot_shortage_behavior.model_dump()
        ),
        analyst_capacity=AnalystCapacity(
            profiles=[
                DayProfile(**p.model_dump())
                for p in schema.analyst_capacity.profiles
            ],
            default_profile_id=schema.analyst_capacity.default_profile_id,
            day_overrides=schema.analyst_capacity.day_overrides,
        ),
        analyst_shortage_behavior=ShortageBehavior(
            **schema.analyst_shortage_behavior.model_dump()
        ),
        max_test_instances=schema.max_test_instances,
        max_concurrent_experiments=schema.max_concurrent_experiments,
        experiment_timeout_minutes=schema.experiment_timeout_minutes,
        max_stored_test_runs=schema.max_stored_test_runs,
        test_cleanup_policy=schema.test_cleanup_policy,
    )


def _change_to_response(
    change: OperationalSettingsChange,
) -> OperationalSettingsChangeResponse:
    return OperationalSettingsChangeResponse(
        id=change.id,
        changed_by=change.changed_by,
        changed_at=change.changed_at,
        changes=[
            SettingChangeResponse(path=c.path, previous=c.previous, new=c.new)
            for c in change.changes
        ],
    )
