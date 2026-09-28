from __future__ import annotations

from uuid import UUID

from src.application.dtos.simulation_dtos import GenerateEventBatchInput
from src.application.ports.simulation_scenario_port import (
    OutputMode,
    ScenarioStatus,
    SimulationScenarioRecord,
)
from src.infrastructure.core.config import genai_config
from src.infrastructure.entrypoint.simulator.celery.celery_app import app
from src.infrastructure.entrypoint.simulator.celery.factories import (
    get_alert_dispatch_gateway,
    get_event_sink,
    get_generate_event_batch_use_case,
    get_record_tick_result_use_case,
    get_simulation_scenario_repository,
)


@app.task(name="event_simulation.tick", bind=True, max_retries=0)
def tick(self, scenario_id: str) -> dict:
    """Self-rescheduling tick loop for one RUNNING scenario - see
    application/use_cases/event_simulation/{generate_event_batch,
    record_tick_result}.py for the actual generation/state-transition logic
    this task orchestrates. No Celery beat: each successful, non-exhausted
    tick schedules its own successor via apply_async(countdown=...)."""
    repository = get_simulation_scenario_repository()
    record_tick = get_record_tick_result_use_case()

    scenario = repository.get(UUID(scenario_id))
    if scenario is None or scenario.status != ScenarioStatus.RUNNING:
        return {"scenario_id": scenario_id, "rescheduled": False}

    window_start = scenario.last_tick_offset_seconds
    window_end = window_start + genai_config.EVENT_SIMULATOR_TICK_SECONDS

    try:
        output = get_generate_event_batch_use_case().execute(
            GenerateEventBatchInput(
                scenario=scenario,
                window_start_seconds=window_start,
                window_end_seconds=window_end,
                max_events=genai_config.EVENT_SIMULATOR_MAX_EVENTS_PER_TICK,
            )
        )
        if output.rows:
            _write_rows(scenario, output.rows)

        updated = record_tick.execute(
            scenario_id=scenario.id,
            events_generated=output.events_generated,
            tick_offset_seconds=window_end,
            schedule_exhausted=output.schedule_exhausted,
        )
    except Exception as exc:  # noqa: BLE001 - a failed tick must not retry-storm
        record_tick.record_failure(scenario.id, str(exc))
        return {"scenario_id": scenario_id, "rescheduled": False, "error": str(exc)}

    if not output.schedule_exhausted and updated.status == ScenarioStatus.RUNNING:
        tick.apply_async(
            args=[scenario_id], countdown=genai_config.EVENT_SIMULATOR_TICK_SECONDS
        )
        return {"scenario_id": scenario_id, "rescheduled": True}

    return {"scenario_id": scenario_id, "rescheduled": False}


def _write_rows(scenario: SimulationScenarioRecord, rows: list[dict]) -> None:
    if scenario.output_mode == OutputMode.DATASET:
        if not scenario.target_dataset_name:
            raise ValueError(
                "Scenario is missing target_dataset_name for DATASET output_mode"
            )
        get_event_sink().write_batch(scenario.target_dataset_name, rows)
        return

    # LIVE_PIPELINE - dispatched one at a time, deliberately sequential (see
    # AlertDispatchGateway's docstring: never parallelize simulator load
    # against aria-worker's Celery pool).
    dispatcher = get_alert_dispatch_gateway()
    for row in rows:
        dispatcher.dispatch(row, created_by="event-simulator")
