from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated
from uuid import uuid4

from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException, status

from src.application.ports.configuration_deploy_request_port import ConfigurationDeployRequest
from src.application.ports.local_auth_port import LocalRole, LocalUser
from src.application.use_cases.configurations.activate_configuration import ConfigurationNotFoundError, ConfigurationNotTestedError
from src.application.use_cases.configurations.test_configuration import _diff, _record_values
from src.infrastructure.entrypoint.api.factories.configuration_factory import get_activate_configuration_use_case, get_configuration_repository
from src.infrastructure.entrypoint.api.routers.auth_router import get_current_user
from src.infrastructure.entrypoint.api.schemas import (
    ConfigurationChangeResponse, ConfigurationDeployRequestResponse,
    ConfigurationDeployRequestPreviewResponse, CreateConfigurationDeployRequest,
)
from src.infrastructure.persistence.database.dynamodb.repositories.configuration_deploy_request_repository import DynamoConfigurationDeployRequestRepository


router = APIRouter(prefix="/configuration-deploy-requests", tags=["configuration deploy requests"])


def _repository() -> DynamoConfigurationDeployRequestRepository:
    return DynamoConfigurationDeployRequestRepository()


def _require_role(user: LocalUser, *roles: LocalRole) -> None:
    if user.role not in roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Role is not permitted for this action")


def _response(request: ConfigurationDeployRequest) -> ConfigurationDeployRequestResponse:
    return ConfigurationDeployRequestResponse(
        **{**request.__dict__, "changes": [ConfigurationChangeResponse(**change) for change in request.changes]}
    )


def _preview(target_configuration_id: str, target_version: int) -> dict:
    configurations = get_configuration_repository()
    target = configurations.get(target_configuration_id, target_version)
    if target is None:
        raise HTTPException(status_code=404, detail="Target configuration version not found")
    if not target.ever_tested:
        raise HTTPException(status_code=422, detail="Target configuration version must pass a test before requesting deployment")
    current = configurations.get_active()
    return {
        "target": target, "current": current,
        "changes": _diff(_record_values(current), _record_values(target)) if current else _diff({}, _record_values(target)),
    }


@router.get("/preview", response_model=ConfigurationDeployRequestPreviewResponse)
def preview_deploy_request(
    target_configuration_id: str,
    target_version: int,
    user: Annotated[LocalUser, Depends(get_current_user)],
):
    _require_role(user, LocalRole.CHANNEL_MANAGER)
    preview = _preview(target_configuration_id, target_version)
    current = preview["current"]
    return ConfigurationDeployRequestPreviewResponse(
        target_configuration_id=target_configuration_id, target_version=target_version,
        current_configuration_id=current.configuration_id if current else None,
        current_version=current.version if current else None,
        changes=[ConfigurationChangeResponse(**change) for change in preview["changes"]],
    )


@router.post("", response_model=ConfigurationDeployRequestResponse, status_code=status.HTTP_201_CREATED)
def create_deploy_request(
    request: CreateConfigurationDeployRequest,
    user: Annotated[LocalUser, Depends(get_current_user)],
):
    _require_role(user, LocalRole.CHANNEL_MANAGER)
    preview = _preview(request.target_configuration_id, request.target_version)
    target, current = preview["target"], preview["current"]
    deploy_request = ConfigurationDeployRequest(
        id=str(uuid4()), target_configuration_id=target.configuration_id, target_version=target.version,
        current_configuration_id=current.configuration_id if current else None,
        current_version=current.version if current else None,
        title=request.title.strip(), message=request.message.strip(),
        changes=preview["changes"],
        requested_by=user.name, requested_at=datetime.now(timezone.utc),
    )
    return _response(_repository().create(deploy_request))


@router.get("", response_model=list[ConfigurationDeployRequestResponse])
def list_deploy_requests(user: Annotated[LocalUser, Depends(get_current_user)]):
    _require_role(user, LocalRole.MANAGER, LocalRole.RELEASE_MANAGER)
    return [_response(request) for request in _repository().list()]


@router.post("/{request_id}/approve", response_model=ConfigurationDeployRequestResponse)
def approve_deploy_request(
    request_id: str,
    user: Annotated[LocalUser, Depends(get_current_user)],
):
    _require_role(user, LocalRole.MANAGER, LocalRole.RELEASE_MANAGER)
    requests = _repository()
    deploy_request = requests.get(request_id)
    if deploy_request is None:
        raise HTTPException(status_code=404, detail="Deploy request not found")
    if deploy_request.status != "pending":
        raise HTTPException(status_code=409, detail="Deploy request has already been processed")
    try:
        get_activate_configuration_use_case().execute(deploy_request.target_configuration_id, deploy_request.target_version)
    except ConfigurationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConfigurationNotTestedError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        approved = requests.approve(request_id, user.name, datetime.now(timezone.utc))
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            raise HTTPException(status_code=409, detail="Deploy request has already been processed") from exc
        raise
    return _response(approved)
