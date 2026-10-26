from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from src.application.use_cases.configurations.activate_configuration import (
    ActivateConfigurationUseCase,
    ConfigurationActivationConflictError,
    ConfigurationNotFoundError,
    ConfigurationNotTestedError,
)
from src.application.use_cases.configurations.create_configuration import (
    ConfigurationVersionConflictError,
    CreateConfigurationUseCase,
)
from src.application.use_cases.configurations.get_active_configuration import (
    GetActiveConfigurationUseCase,
)
from src.application.use_cases.configurations.get_configuration import (
    GetConfigurationUseCase,
)
from src.application.use_cases.configurations.get_configuration_graph import (
    GetConfigurationGraphUseCase,
)
from src.application.use_cases.configurations.list_configuration_versions import (
    ListConfigurationVersionsUseCase,
)
from src.application.use_cases.configurations.list_configurations import (
    ListConfigurationsUseCase,
)
from src.application.use_cases.configurations.test_configuration import (
    ConfigurationBaseNotFoundError,
    PreviewConfigurationUseCase,
)
from src.infrastructure.entrypoint.api.configuration_mapper import (
    input_from_request,
    to_detail_response,
    to_graph_node_response,
    to_summary_response,
)
from src.infrastructure.entrypoint.api.factories.configuration_factory import (
    get_activate_configuration_use_case,
    get_configuration_graph_use_case,
    get_create_configuration_use_case,
    get_get_active_configuration_use_case,
    get_get_configuration_use_case,
    get_list_configuration_versions_use_case,
    get_list_configurations_use_case,
    get_test_configuration_use_case,
)
from src.infrastructure.entrypoint.api.schemas import (
    ConfigurationChangeResponse,
    ConfigurationDetailResponse,
    ConfigurationGraphNodeResponse,
    ConfigurationSummaryResponse,
    CreateConfigurationRequest,
    TestConfigurationResponse,
)

router = APIRouter(prefix="/configurations", tags=["configurations"])
configuration_test_router = APIRouter(prefix="/configuration", tags=["configurations"])


@configuration_test_router.post("/test", response_model=TestConfigurationResponse)
def test_configuration(
    request: CreateConfigurationRequest,
    use_case: Annotated[
        PreviewConfigurationUseCase, Depends(get_test_configuration_use_case)
    ],
):
    try:
        result = use_case.execute(input_from_request(request))
    except ConfigurationVersionConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except ConfigurationBaseNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return TestConfigurationResponse(
        valid=result.valid,
        changes=[
            ConfigurationChangeResponse(**change.__dict__) for change in result.changes
        ],
        warnings=result.warnings,
    )


@router.post(
    "", response_model=ConfigurationDetailResponse, status_code=status.HTTP_201_CREATED
)
def create_configuration(
    request: CreateConfigurationRequest,
    use_case: Annotated[
        CreateConfigurationUseCase, Depends(get_create_configuration_use_case)
    ],
):
    try:
        record = use_case.execute(input_from_request(request))
    except ConfigurationVersionConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return to_detail_response(record)


@router.get("", response_model=list[ConfigurationSummaryResponse])
def list_configurations(
    use_case: Annotated[
        ListConfigurationsUseCase, Depends(get_list_configurations_use_case)
    ],
):
    return [to_summary_response(record) for record in use_case.execute()]


@router.get("/active", response_model=ConfigurationDetailResponse)
def get_active_configuration(
    use_case: Annotated[
        GetActiveConfigurationUseCase, Depends(get_get_active_configuration_use_case)
    ],
):
    record = use_case.execute()
    if record is None:
        raise HTTPException(status_code=404, detail="No active configuration")
    return to_detail_response(record)


@router.get("/graph", response_model=list[ConfigurationGraphNodeResponse])
def get_configuration_graph(
    use_case: Annotated[
        GetConfigurationGraphUseCase, Depends(get_configuration_graph_use_case)
    ],
):
    """Read every configuration version with its parent and promotion comment."""
    return [to_graph_node_response(node) for node in use_case.execute()]


@router.get("/{configuration_id}", response_model=list[ConfigurationSummaryResponse])
def list_configuration_versions(
    configuration_id: str,
    use_case: Annotated[
        ListConfigurationVersionsUseCase,
        Depends(get_list_configuration_versions_use_case),
    ],
):
    records = use_case.execute(configuration_id)
    if not records:
        raise HTTPException(status_code=404, detail="Configuration not found")
    return [to_summary_response(record) for record in records]


@router.get(
    "/{configuration_id}/versions/{version}",
    response_model=ConfigurationDetailResponse,
)
def get_configuration(
    configuration_id: str,
    version: int,
    use_case: Annotated[
        GetConfigurationUseCase, Depends(get_get_configuration_use_case)
    ],
):
    record = use_case.execute(configuration_id, version)
    if record is None:
        raise HTTPException(status_code=404, detail="Configuration not found")
    return to_detail_response(record)


@router.post(
    "/{configuration_id}/versions/{version}/activate",
    response_model=ConfigurationDetailResponse,
)
def activate_configuration(
    configuration_id: str,
    version: int,
    use_case: Annotated[
        ActivateConfigurationUseCase, Depends(get_activate_configuration_use_case)
    ],
):
    try:
        active = get_get_active_configuration_use_case().execute()
        expected_current = (
            (active.configuration_id, active.version) if active is not None else None
        )
        record = use_case.execute(
            configuration_id, version, expected_current=expected_current
        )
    except ConfigurationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ConfigurationNotTestedError, ConfigurationActivationConflictError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return to_detail_response(record)
