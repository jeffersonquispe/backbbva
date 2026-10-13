from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.application.dtos.test_run_dtos import DeleteTestRunsInput, StartTestRunInput
from src.application.errors import NotFoundError, ValidationError
from src.application.ports.test_run_port import TestRunConfig
from src.application.use_cases.test_runs.dataset_sampling import (
    InsufficientSampleDataError,
)
from src.application.use_cases.test_runs.delete_test_runs import DeleteTestRunsUseCase
from src.application.use_cases.test_runs.get_test_case_detail import (
    GetTestCaseDetailUseCase,
)
from src.application.use_cases.test_runs.get_test_run import GetTestRunUseCase
from src.application.use_cases.test_runs.list_test_runs import ListTestRunsUseCase
from src.application.use_cases.test_runs.start_test_run import StartTestRunUseCase
from src.application.use_cases.test_runs.token_usage import sum_step_tokens
from src.domain.alerts.exceptions import AlertPayloadTooLargeError
from src.domain.configurations.entities import (
    ConfigurationRef,
)
from src.infrastructure.entrypoint.api.factories.test_run_factory import (
    get_delete_test_runs_use_case,
    get_get_test_case_detail_use_case,
    get_get_test_run_use_case,
    get_list_test_runs_use_case,
    get_start_test_run_use_case,
)
from src.infrastructure.entrypoint.api.schemas import (
    DeleteTestRunsRequest,
    DeleteTestRunsResponse,
    StartTestRunRequest,
    StartTestRunResponse,
    TestCaseDetailResponse,
    TestRunDetailResponse,
    TestRunResponse,
    WorkflowStepResponse,
)

router = APIRouter(tags=["test-runs"])


@router.post(
    "/test-runs",
    response_model=StartTestRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_test_run(
    request: StartTestRunRequest,
    use_case: Annotated[StartTestRunUseCase, Depends(get_start_test_run_use_case)],
):
    try:
        return use_case.execute(
            StartTestRunInput(
                name=request.name,
                dataset_name=request.dataset_name,
                config=TestRunConfig(
                    prompt_overrides=request.config.prompt_overrides,
                    model_overrides=request.config.model_overrides,
                    max_feedback_iterations=request.config.max_feedback_iterations,
                    configuration_ref=(
                        ConfigurationRef(
                            configuration_id=request.config.configuration_ref.configuration_id,
                            version=request.config.configuration_ref.version,
                        )
                        if request.config.configuration_ref is not None
                        else None
                    ),
                    schema_version=request.config.schema_version,
                ),
                sample_size=request.sample_size,
                sample_distribution=request.sample_distribution,
            )
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValidationError, InsufficientSampleDataError, AlertPayloadTooLargeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/test-runs", response_model=list[TestRunResponse])
def list_test_runs(
    use_case: Annotated[ListTestRunsUseCase, Depends(get_list_test_runs_use_case)],
    order: Literal["asc", "desc"] = Query(default="desc"),
):
    return use_case.execute(order=order)


@router.delete("/test-runs", response_model=DeleteTestRunsResponse)
def delete_test_runs(
    request: DeleteTestRunsRequest,
    use_case: Annotated[DeleteTestRunsUseCase, Depends(get_delete_test_runs_use_case)],
):
    result = use_case.execute(DeleteTestRunsInput(test_run_ids=request.test_run_ids))
    return DeleteTestRunsResponse(
        deleted_test_runs=result.deleted_test_runs,
        deleted_cases=result.deleted_cases,
    )


@router.get("/test-runs/{test_run_id}", response_model=TestRunDetailResponse)
def get_test_run(
    test_run_id: UUID,
    use_case: Annotated[GetTestRunUseCase, Depends(get_get_test_run_use_case)],
):
    detail = use_case.execute(test_run_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Test run not found")
    return detail


@router.get(
    "/test-runs/{test_run_id}/cases/{workflow_execution_id}",
    response_model=TestCaseDetailResponse,
)
def get_test_case_detail(
    test_run_id: UUID,
    workflow_execution_id: UUID,
    use_case: Annotated[
        GetTestCaseDetailUseCase, Depends(get_get_test_case_detail_use_case)
    ],
):
    result = use_case.execute(workflow_execution_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Test case not found")
    workflow, steps = result
    if workflow.test_run_id != test_run_id:
        raise HTTPException(status_code=404, detail="Test case not found")
    input_tokens, output_tokens = sum_step_tokens(steps)
    return TestCaseDetailResponse(
        workflow_execution_id=workflow.id,
        alert_id=workflow.alert_id,
        status=workflow.status,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        steps=[
            WorkflowStepResponse(
                id=step.id,
                step_name=step.step_name,
                status=step.status,
                attempt=step.attempt,
                input=step.input,
                output=step.output,
                error=step.error,
                started_at=step.started_at,
                finished_at=step.finished_at,
            )
            for step in steps
        ],
        schema_comparison=workflow.schema_comparison,
        schema_version=(workflow.input or {}).get("schema_version"),
        configuration_ref=(workflow.input or {}).get("configuration_ref"),
    )
