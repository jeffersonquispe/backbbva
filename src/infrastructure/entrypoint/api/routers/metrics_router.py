from __future__ import annotations

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from src.application.dtos.metrics_dtos import MetricsQueryInput
from src.application.use_cases.metrics.get_agent_metrics import GetAgentMetrics
from src.application.use_cases.metrics.get_live_alert_funnel import GetLiveAlertFunnel
from src.application.use_cases.metrics.get_metrics_overview import GetMetricsOverview
from src.application.use_cases.metrics.get_technical_metrics import GetTechnicalMetrics
from src.application.use_cases.metrics.get_version_events import GetVersionEvents
from src.infrastructure.entrypoint.api.authorization import require_permission
from src.infrastructure.entrypoint.api.factories.metrics_factory import (
    get_agent_metrics_use_case,
    get_live_alert_funnel_use_case,
    get_metrics_overview_use_case,
    get_technical_metrics_use_case,
    get_version_events_use_case,
)
from src.infrastructure.entrypoint.api.metrics_query_params import (
    MetricsQueryParams,
    metrics_query_params,
)
from src.infrastructure.entrypoint.api.schemas import (
    AgentMetricsResponse,
    LiveAlertFunnelResponse,
    MetricsOverviewResponse,
    TechnicalMetricsResponse,
    VersionEventResponse,
)

router = APIRouter(prefix="/metrics", tags=["metrics"])


def _input(params: MetricsQueryParams) -> MetricsQueryInput:
    return MetricsQueryInput(from_=params.from_, to=params.to, filters=params.filters)


@router.get(
    "/overview",
    response_model=MetricsOverviewResponse,
    dependencies=[Depends(require_permission("dashboard"))],
)
def get_metrics_overview(
    params: Annotated[MetricsQueryParams, Depends(metrics_query_params)],
    use_case: Annotated[GetMetricsOverview, Depends(get_metrics_overview_use_case)],
):
    try:
        output = use_case.execute(_input(params))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return MetricsOverviewResponse.model_validate(asdict(output))


@router.get(
    "/agent",
    response_model=AgentMetricsResponse,
    dependencies=[Depends(require_permission("monitor"))],
)
def get_agent_metrics(
    params: Annotated[MetricsQueryParams, Depends(metrics_query_params)],
    use_case: Annotated[GetAgentMetrics, Depends(get_agent_metrics_use_case)],
):
    try:
        output = use_case.execute(_input(params))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return AgentMetricsResponse.model_validate(asdict(output))


def technical_query_params(
    params: Annotated[MetricsQueryParams, Depends(metrics_query_params)],
    step_name: Annotated[list[str] | None, Query()] = None,
    model: Annotated[list[str] | None, Query()] = None,
) -> MetricsQueryParams:
    """The shared range/alert filters plus step_name / model (repeatable)."""
    extra = {"step_name": step_name, "model": model}
    params.filters.update({name: values for name, values in extra.items() if values})
    return params


@router.get(
    "/technical",
    response_model=TechnicalMetricsResponse,
    dependencies=[Depends(require_permission("monitor"))],
)
def get_technical_metrics(
    params: Annotated[MetricsQueryParams, Depends(technical_query_params)],
    use_case: Annotated[GetTechnicalMetrics, Depends(get_technical_metrics_use_case)],
):
    try:
        output = use_case.execute(_input(params))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return TechnicalMetricsResponse.model_validate(asdict(output))


@router.get(
    "/live",
    response_model=LiveAlertFunnelResponse,
    dependencies=[Depends(require_permission("dashboard"))],
)
def get_live_alert_funnel(
    use_case: Annotated[GetLiveAlertFunnel, Depends(get_live_alert_funnel_use_case)],
):
    """"Tiempo real" funnel: alerts in each live state right now (not a
    range - reads the status index, not the rollups)."""
    return LiveAlertFunnelResponse.model_validate(asdict(use_case.execute()))


@router.get(
    "/version-events",
    response_model=list[VersionEventResponse],
    dependencies=[Depends(require_permission("dashboard"))],
)
def get_version_events(
    params: Annotated[MetricsQueryParams, Depends(metrics_query_params)],
    use_case: Annotated[GetVersionEvents, Depends(get_version_events_use_case)],
):
    try:
        return [VersionEventResponse.model_validate(asdict(event)) for event in use_case.execute(params.from_, params.to)]
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
