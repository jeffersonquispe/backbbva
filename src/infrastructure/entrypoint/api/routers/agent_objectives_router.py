from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from src.application.ports.local_auth_port import LocalRole, LocalUser
from src.application.use_cases.agent.evaluate_global_pipeline import (
    GLOBAL_PIPELINE_VERIFICATION_ID,
    GlobalPipelineEvaluationError,
)
from src.application.use_cases.agent.manage_agent_objective import (
    AgentObjectiveNotFoundError,
    AgentObjectivePolicyError,
)
from src.infrastructure.agents.factories import get_agent_verification_repository
from src.infrastructure.entrypoint.api.factories.agent_objective_factory import (
    get_activate_agent_objective_version,
    get_agent_objective_repository,
    get_create_agent_objective_version,
    get_start_global_pipeline_evaluation,
)
from src.infrastructure.entrypoint.api.routers.auth_router import get_current_user
from src.infrastructure.entrypoint.api.schemas.agent_objectives import (
    ActivateAgentObjectiveRequest,
    AgentObjectiveResponse,
    GlobalPipelineEvaluationResponse,
    StartGlobalPipelineEvaluationRequest,
)

router = APIRouter(prefix="/agent/objectives", tags=["agent-objectives"])
_OBJECTIVE_EDITORS = {LocalRole.MANAGER, LocalRole.RELEASE_MANAGER}


@router.get("", response_model=list[AgentObjectiveResponse])
def list_objective_versions(
    user: Annotated[LocalUser, Depends(get_current_user)],
):
    return get_agent_objective_repository().list_versions("global_fraud_effectiveness")


@router.get("/active", response_model=AgentObjectiveResponse)
def get_active_objective(
    user: Annotated[LocalUser, Depends(get_current_user)],
):
    objective = get_agent_objective_repository().get_active("global_fraud_effectiveness")
    if objective is None:
        raise HTTPException(status_code=404, detail={"code": "ACTIVE_OBJECTIVE_NOT_FOUND"})
    return objective


@router.post("", response_model=AgentObjectiveResponse, status_code=status.HTTP_201_CREATED)
def create_objective_version(
    user: Annotated[LocalUser, Depends(get_current_user)],
):
    if user.role not in _OBJECTIVE_EDITORS:
        raise HTTPException(status_code=403, detail="Role cannot create objectives")
    try:
        return get_create_agent_objective_version().execute(created_by=str(user.id))
    except AgentObjectivePolicyError as error:
        raise HTTPException(status_code=422, detail={"code": "OBJECTIVE_POLICY"}) from error


@router.post("/{version}/activate", response_model=AgentObjectiveResponse)
def activate_objective_version(
    version: int,
    request: ActivateAgentObjectiveRequest,
    user: Annotated[LocalUser, Depends(get_current_user)],
):
    if user.role not in _OBJECTIVE_EDITORS:
        raise HTTPException(status_code=403, detail="Role cannot activate objectives")
    try:
        return get_activate_agent_objective_version().execute(
            version=version,
            actor_id=str(user.id),
            expected_active_version=request.expected_active_version,
        )
    except AgentObjectiveNotFoundError as error:
        raise HTTPException(status_code=404, detail={"code": "OBJECTIVE_NOT_FOUND"}) from error
    except AgentObjectivePolicyError as error:
        raise HTTPException(status_code=409, detail={"code": "OBJECTIVE_CONFLICT"}) from error


@router.post(
    "/evaluations/global",
    response_model=GlobalPipelineEvaluationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_global_pipeline_evaluation(
    request: StartGlobalPipelineEvaluationRequest,
    user: Annotated[LocalUser, Depends(get_current_user)],
):
    if user.role not in _OBJECTIVE_EDITORS:
        raise HTTPException(status_code=403, detail="Role cannot evaluate models")
    try:
        result = get_start_global_pipeline_evaluation().execute(
            snapshot_id=request.snapshot_id,
            candidate_model_id=request.candidate_model_id,
        )
        return _evaluation_response(result)
    except GlobalPipelineEvaluationError as error:
        raise HTTPException(status_code=409, detail={"code": "GLOBAL_EVALUATION_POLICY"}) from error


@router.get(
    "/evaluations/global/{snapshot_id}",
    response_model=GlobalPipelineEvaluationResponse,
)
def get_global_pipeline_evaluation(
    snapshot_id: str,
    user: Annotated[LocalUser, Depends(get_current_user)],
):
    result = get_agent_verification_repository().get(
        snapshot_id, GLOBAL_PIPELINE_VERIFICATION_ID
    )
    if result is None:
        raise HTTPException(status_code=404, detail={"code": "GLOBAL_EVALUATION_NOT_FOUND"})
    return _evaluation_response(result)


def _evaluation_response(result):
    return {
        "snapshot_id": result.subject_id,
        "status": result.status,
        "verifier": result.verifier,
        "safe_metrics": result.safe_metrics,
        "error_code": result.error_code,
    }
