from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from src.application.dtos.alert_schema_dtos import (
    ApproveAlertSchemaInput,
    CreateAlertSchemaSuggestionInput,
    SaveAlertSchemaDraftInput,
)
from src.application.ports.alert_schema_port import AlertSchemaField
from src.application.ports.local_auth_port import LocalRole, LocalUser
from src.application.use_cases.alert_schema.approve_schema import (
    ImpactAcknowledgementRequired,
    SelfApprovalError,
)
from src.infrastructure.entrypoint.api.authorization import require_permission
from src.infrastructure.entrypoint.api.factories.alert_schema_factory import *
from src.infrastructure.entrypoint.api.routers.auth_router import get_current_user
from src.infrastructure.entrypoint.api.schemas import (
    AlertSchemaPresenceResponse,
    AlertSchemaSuggestionResponse,
    AlertSchemaVersionResponse,
    ApproveAlertSchemaRequest,
    CreateAlertSchemaDraft,
    CreateAlertSchemaSuggestionRequest,
)

router = APIRouter(prefix="/alert-schema", tags=["alert schema"])

def _response(schema):
    return AlertSchemaVersionResponse.model_validate(schema, from_attributes=True)

def _require_schema_read(user: Annotated[LocalUser, Depends(get_current_user)]) -> LocalUser:
    if user.role not in {LocalRole.MANAGER, LocalRole.RELEASE_MANAGER, LocalRole.DATA_ANALYST}:
        raise HTTPException(status_code=403, detail="Permission is not granted")
    return user

@router.get("/active", response_model=AlertSchemaVersionResponse | None)
def get_active_schema(_: Annotated[LocalUser, Depends(get_current_user)]):
    schema = get_get_active_alert_schema_use_case().execute()
    return _response(schema) if schema else None

@router.get("/versions", response_model=list[AlertSchemaVersionResponse])
def list_schema_versions(_: Annotated[LocalUser, Depends(_require_schema_read)]):
    return [_response(item) for item in get_list_alert_schema_versions_use_case().execute()]

@router.get("/versions/{version}", response_model=AlertSchemaVersionResponse)
def get_schema_version(version: int, _: Annotated[LocalUser, Depends(_require_schema_read)]):
    schema = get_get_alert_schema_version_use_case().execute(version)
    if schema is None: raise HTTPException(status_code=404, detail="Alert schema version not found")
    return _response(schema)

@router.post("/drafts", response_model=AlertSchemaVersionResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("alert_schema"))])
def save_schema_draft(request: CreateAlertSchemaDraft, _: Annotated[LocalUser, Depends(get_current_user)]):
    try:
        schema = get_save_alert_schema_draft_use_case().execute(SaveAlertSchemaDraftInput([AlertSchemaField(**item.model_dump()) for item in request.fields], request.field_roles, request.version, request.based_on_version))
    except ValueError as exc: raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _response(schema)

@router.post("/versions/{version}/propose", response_model=AlertSchemaVersionResponse, dependencies=[Depends(require_permission("alert_schema"))])
def propose_schema_version(version: int, user: Annotated[LocalUser, Depends(get_current_user)]):
    try: return _response(get_propose_alert_schema_use_case().execute(version, str(user.id)))
    except LookupError as exc: raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc: raise HTTPException(status_code=409, detail=str(exc)) from exc

@router.post("/versions/{version}/approve", response_model=AlertSchemaVersionResponse, dependencies=[Depends(require_permission("alert_schema"))])
def approve_schema_version(version: int, user: Annotated[LocalUser, Depends(get_current_user)], request: ApproveAlertSchemaRequest | None = None):
    try: return _response(get_approve_alert_schema_use_case().execute(ApproveAlertSchemaInput(version, str(user.id), request.impact_acknowledged if request else False)))
    except LookupError as exc: raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SelfApprovalError as exc: raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ImpactAcknowledgementRequired as exc: raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc: raise HTTPException(status_code=409, detail=str(exc)) from exc

@router.post("/versions/{version}/reject", response_model=AlertSchemaVersionResponse, dependencies=[Depends(require_permission("alert_schema"))])
def reject_schema_version(version: int, _: Annotated[LocalUser, Depends(get_current_user)]):
    try: return _response(get_reject_alert_schema_use_case().execute(version))
    except LookupError as exc: raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc: raise HTTPException(status_code=409, detail=str(exc)) from exc

@router.post("/suggestions", response_model=AlertSchemaSuggestionResponse, status_code=201)
def create_suggestion(request: CreateAlertSchemaSuggestionRequest, user: Annotated[LocalUser, Depends(get_current_user)]):
    if user.role not in {LocalRole.FRAUD_ANALYST, LocalRole.OPS_ANALYST}: raise HTTPException(status_code=403, detail="Role is not permitted for this action")
    return get_create_alert_schema_suggestion_use_case().execute(CreateAlertSchemaSuggestionInput(request.alert_id, request.field, request.location, request.comment, str(user.id)))

@router.get("/suggestions", response_model=list[AlertSchemaSuggestionResponse], dependencies=[Depends(require_permission("alert_schema"))])
def list_suggestions(user: Annotated[LocalUser, Depends(get_current_user)]):
    if user.role not in {LocalRole.MANAGER, LocalRole.RELEASE_MANAGER, LocalRole.DATA_ANALYST}: raise HTTPException(status_code=403, detail="Permission is not granted")
    return get_list_alert_schema_suggestions_use_case().execute()


@router.get("/presence", response_model=AlertSchemaPresenceResponse | None, dependencies=[Depends(require_permission("alert_schema"))])
def get_presence_report(_: Annotated[LocalUser, Depends(get_current_user)]):
    report = get_alert_schema_presence_report_repository().get_latest()
    return report
