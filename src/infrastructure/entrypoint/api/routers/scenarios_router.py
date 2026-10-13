from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.application.dtos.simulation_dtos import (
    CreateSimulationScenarioInput,
    SeedSimulationFromDatasetInput,
    UpdateSimulationScenarioInput,
)
from src.application.ports.simulation_scenario_port import (
    FieldGenerator,
    RateInterval,
    ScenarioStatus,
)
from src.application.use_cases.event_simulation.create_simulation_scenario import (
    CreateSimulationScenarioUseCase,
)
from src.application.use_cases.event_simulation.delete_simulation_scenario import (
    DeleteSimulationScenarioUseCase,
)
from src.application.use_cases.event_simulation.generate_event_batch import (
    GenerateEventBatchUseCase,
)
from src.application.use_cases.event_simulation.get_simulation_scenario import (
    GetSimulationScenarioUseCase,
)
from src.application.use_cases.event_simulation.get_simulation_status import (
    GetSimulationStatusUseCase,
)
from src.application.use_cases.event_simulation.list_simulation_scenarios import (
    ListSimulationScenariosUseCase,
)
from src.application.use_cases.event_simulation.pause_simulation import (
    PauseSimulationUseCase,
)
from src.application.use_cases.event_simulation.seed_simulation_from_dataset import (
    SeedSimulationFromDatasetUseCase,
)
from src.application.use_cases.event_simulation.start_simulation import (
    StartSimulationUseCase,
)
from src.application.use_cases.event_simulation.stop_simulation import (
    StopSimulationUseCase,
)
from src.application.use_cases.event_simulation.update_simulation_scenario import (
    UpdateSimulationScenarioUseCase,
)
from src.infrastructure.entrypoint.api.factories.simulation_scenario_factory import (
    get_create_simulation_scenario_use_case,
    get_delete_simulation_scenario_use_case,
    get_generate_event_batch_use_case,
    get_get_simulation_scenario_use_case,
    get_get_simulation_status_use_case,
    get_list_simulation_scenarios_use_case,
    get_pause_simulation_use_case,
    get_seed_simulation_from_dataset_use_case,
    get_start_simulation_use_case,
    get_stop_simulation_use_case,
    get_update_simulation_scenario_use_case,
)
from src.infrastructure.entrypoint.api.schemas import (
    CreateSimulationScenarioRequest,
    FieldGeneratorSchema,
    RateIntervalSchema,
    SeedSimulationFromDatasetRequest,
    SimulationScenarioResponse,
    SimulationStatusResponse,
    UpdateSimulationScenarioRequest,
)

router = APIRouter(prefix="/scenarios", tags=["scenarios"])


def _to_rate_interval(schema: RateIntervalSchema) -> RateInterval:
    return RateInterval(
        start_offset_seconds=schema.start_offset_seconds,
        end_offset_seconds=schema.end_offset_seconds,
        events_per_minute=schema.events_per_minute,
    )


def _to_field_generator(schema: FieldGeneratorSchema) -> FieldGenerator:
    return FieldGenerator(
        kind=schema.kind,
        value=schema.value,
        weights=schema.weights,
        params=schema.params,
        system_prompt=schema.system_prompt,
        user_prompt_template=schema.user_prompt_template,
        model=schema.model,
        temperature=schema.temperature,
        seed_dataset_name=schema.seed_dataset_name,
        seed_field=schema.seed_field,
    )


def _to_response(scenario) -> SimulationScenarioResponse:
    return SimulationScenarioResponse(
        id=scenario.id,
        name=scenario.name,
        status=scenario.status,
        output_mode=scenario.output_mode,
        rate_schedule=[
            RateIntervalSchema(
                start_offset_seconds=interval.start_offset_seconds,
                end_offset_seconds=interval.end_offset_seconds,
                events_per_minute=interval.events_per_minute,
            )
            for interval in scenario.rate_schedule
        ],
        field_specs={
            name: FieldGeneratorSchema(
                kind=generator.kind,
                value=generator.value,
                weights=generator.weights,
                params=generator.params,
                system_prompt=generator.system_prompt,
                user_prompt_template=generator.user_prompt_template,
                model=generator.model,
                temperature=generator.temperature,
                seed_dataset_name=generator.seed_dataset_name,
                seed_field=generator.seed_field,
            )
            for name, generator in scenario.field_specs.items()
        },
        target_dataset_name=scenario.target_dataset_name,
        created_by=scenario.created_by,
        created_at=scenario.created_at,
        updated_at=scenario.updated_at,
        started_at=scenario.started_at,
        events_emitted=scenario.events_emitted,
        last_tick_offset_seconds=scenario.last_tick_offset_seconds,
        error=scenario.error,
    )


@router.post(
    "",
    response_model=SimulationScenarioResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_scenario(
    request: CreateSimulationScenarioRequest,
    use_case: Annotated[
        CreateSimulationScenarioUseCase,
        Depends(get_create_simulation_scenario_use_case),
    ],
):
    try:
        scenario = use_case.execute(
            CreateSimulationScenarioInput(
                name=request.name,
                output_mode=request.output_mode,
                rate_schedule=[_to_rate_interval(i) for i in request.rate_schedule],
                field_specs={
                    name: _to_field_generator(spec)
                    for name, spec in request.field_specs.items()
                }
                if request.field_specs is not None
                else None,
                target_dataset_name=request.target_dataset_name,
                created_by=request.created_by,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_response(scenario)


@router.post("/seed-from-dataset", response_model=dict[str, FieldGeneratorSchema])
def seed_from_dataset(
    request: SeedSimulationFromDatasetRequest,
    use_case: Annotated[
        SeedSimulationFromDatasetUseCase,
        Depends(get_seed_simulation_from_dataset_use_case),
    ],
):
    try:
        field_specs = use_case.execute(
            SeedSimulationFromDatasetInput(dataset_name=request.dataset_name)
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        name: FieldGeneratorSchema(
            kind=generator.kind,
            value=generator.value,
            weights=generator.weights,
            params=generator.params,
        )
        for name, generator in field_specs.items()
    }


@router.get("", response_model=list[SimulationScenarioResponse])
def list_scenarios(
    use_case: Annotated[
        ListSimulationScenariosUseCase, Depends(get_list_simulation_scenarios_use_case)
    ],
    status_filter: ScenarioStatus | None = Query(default=None, alias="status"),
):
    return [_to_response(s) for s in use_case.execute(status=status_filter)]


@router.get("/{scenario_id}", response_model=SimulationScenarioResponse)
def get_scenario(
    scenario_id: UUID,
    use_case: Annotated[
        GetSimulationScenarioUseCase, Depends(get_get_simulation_scenario_use_case)
    ],
):
    scenario = use_case.execute(scenario_id)
    if scenario is None:
        raise HTTPException(status_code=404, detail=f"Scenario {scenario_id} not found")
    return _to_response(scenario)


@router.put("/{scenario_id}", response_model=SimulationScenarioResponse)
def update_scenario(
    scenario_id: UUID,
    request: UpdateSimulationScenarioRequest,
    use_case: Annotated[
        UpdateSimulationScenarioUseCase,
        Depends(get_update_simulation_scenario_use_case),
    ],
):
    try:
        scenario = use_case.execute(
            UpdateSimulationScenarioInput(
                scenario_id=scenario_id,
                name=request.name,
                rate_schedule=(
                    [_to_rate_interval(i) for i in request.rate_schedule]
                    if request.rate_schedule is not None
                    else None
                ),
                field_specs=(
                    {
                        name: _to_field_generator(spec)
                        for name, spec in request.field_specs.items()
                    }
                    if request.field_specs is not None
                    else None
                ),
                target_dataset_name=request.target_dataset_name,
            )
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_response(scenario)


@router.delete("/{scenario_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_scenario(
    scenario_id: UUID,
    use_case: Annotated[
        DeleteSimulationScenarioUseCase,
        Depends(get_delete_simulation_scenario_use_case),
    ],
):
    try:
        use_case.execute(scenario_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{scenario_id}/start", response_model=SimulationScenarioResponse)
def start_scenario(
    scenario_id: UUID,
    use_case: Annotated[StartSimulationUseCase, Depends(get_start_simulation_use_case)],
):
    try:
        scenario = use_case.execute(scenario_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_response(scenario)


@router.post("/{scenario_id}/pause", response_model=SimulationScenarioResponse)
def pause_scenario(
    scenario_id: UUID,
    use_case: Annotated[PauseSimulationUseCase, Depends(get_pause_simulation_use_case)],
):
    try:
        scenario = use_case.execute(scenario_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _to_response(scenario)


@router.post("/{scenario_id}/stop", response_model=SimulationScenarioResponse)
def stop_scenario(
    scenario_id: UUID,
    use_case: Annotated[StopSimulationUseCase, Depends(get_stop_simulation_use_case)],
):
    try:
        scenario = use_case.execute(scenario_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _to_response(scenario)


@router.get("/{scenario_id}/status", response_model=SimulationStatusResponse)
def get_scenario_status(
    scenario_id: UUID,
    use_case: Annotated[
        GetSimulationStatusUseCase, Depends(get_get_simulation_status_use_case)
    ],
):
    try:
        output = use_case.execute(scenario_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return SimulationStatusResponse(
        scenario_id=output.scenario_id,
        status=output.status,
        events_emitted=output.events_emitted,
        last_tick_offset_seconds=output.last_tick_offset_seconds,
        error=output.error,
    )


@router.post("/{scenario_id}/preview", response_model=list[dict])
def preview_scenario(
    scenario_id: UUID,
    get_scenario_use_case: Annotated[
        GetSimulationScenarioUseCase, Depends(get_get_simulation_scenario_use_case)
    ],
    generate_batch_use_case: Annotated[
        GenerateEventBatchUseCase, Depends(get_generate_event_batch_use_case)
    ],
    count: int = Query(default=5, gt=0, le=100),
):
    scenario = get_scenario_use_case.execute(scenario_id)
    if scenario is None:
        raise HTTPException(status_code=404, detail=f"Scenario {scenario_id} not found")
    try:
        return generate_batch_use_case.generate_preview(
            scenario.field_specs, count, seed=None
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
