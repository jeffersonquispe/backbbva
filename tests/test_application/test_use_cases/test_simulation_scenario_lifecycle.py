from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

from src.application.dtos.simulation_dtos import (
    CreateSimulationScenarioInput,
    UpdateSimulationScenarioInput,
)
from src.application.ports.simulation_scenario_port import (
    FieldGenerator,
    GeneratorKind,
    OutputMode,
    RateInterval,
    ScenarioStatus,
    SimulationScenarioRecord,
)
from src.application.use_cases.event_simulation.create_simulation_scenario import (
    CreateSimulationScenarioUseCase,
)
from src.application.use_cases.event_simulation.delete_simulation_scenario import (
    DeleteSimulationScenarioUseCase,
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
from src.application.use_cases.event_simulation.record_tick_result import (
    RecordTickResultUseCase,
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


class InMemorySimulationScenarioRepository:
    def __init__(self) -> None:
        self.scenarios: dict[UUID, SimulationScenarioRecord] = {}

    def create(self, scenario: SimulationScenarioRecord) -> SimulationScenarioRecord:
        self.scenarios[scenario.id] = scenario
        return scenario

    def get(self, scenario_id: UUID) -> SimulationScenarioRecord | None:
        return self.scenarios.get(scenario_id)

    def list(
        self, status: ScenarioStatus | None = None
    ) -> list[SimulationScenarioRecord]:
        values = list(self.scenarios.values())
        if status is None:
            return values
        return [s for s in values if s.status == status]

    def update(
        self, scenario_id: UUID, **changes: Any
    ) -> SimulationScenarioRecord | None:
        current = self.scenarios.get(scenario_id)
        if current is None:
            return None
        # Mirrors InMemoryWorkflowExecutionRepository's convention: a field
        # explicitly present in changes (even as None) overwrites; an absent
        # field keeps its current value - lets callers explicitly clear
        # e.g. `error=None`.
        fields = {f: getattr(current, f) for f in current.__dataclass_fields__}
        for key, value in changes.items():
            fields[key] = value
        updated = SimulationScenarioRecord(**fields)
        self.scenarios[scenario_id] = updated
        return updated

    def delete(self, scenario_id: UUID) -> None:
        self.scenarios.pop(scenario_id, None)


class RecordingSimulationDispatcher:
    def __init__(self) -> None:
        self.dispatched: list[UUID] = []

    def dispatch(self, scenario_id: UUID) -> None:
        self.dispatched.append(scenario_id)


def _create_input(**overrides: Any) -> CreateSimulationScenarioInput:
    defaults = dict(
        name="scenario",
        output_mode=OutputMode.DATASET,
        rate_schedule=[RateInterval(0, 60, events_per_minute=10)],
        field_specs={
            "channel": FieldGenerator(kind=GeneratorKind.CONSTANT, value="app")
        },
        target_dataset_name="synthetic_events",
    )
    defaults.update(overrides)
    return CreateSimulationScenarioInput(**defaults)


def test_create_requires_target_dataset_name_for_dataset_output_mode() -> None:
    repo = InMemorySimulationScenarioRepository()
    use_case = CreateSimulationScenarioUseCase(repo)

    with pytest.raises(ValueError):
        use_case.execute(_create_input(target_dataset_name=None))


def test_create_defaults_to_draft_status() -> None:
    repo = InMemorySimulationScenarioRepository()
    use_case = CreateSimulationScenarioUseCase(repo)

    scenario = use_case.execute(_create_input())

    assert scenario.status == ScenarioStatus.DRAFT
    assert scenario.events_emitted == 0


def test_update_rejects_editing_a_running_scenario() -> None:
    repo = InMemorySimulationScenarioRepository()
    scenario = CreateSimulationScenarioUseCase(repo).execute(_create_input())
    repo.update(scenario.id, status=ScenarioStatus.RUNNING)
    use_case = UpdateSimulationScenarioUseCase(repo)

    with pytest.raises(ValueError):
        use_case.execute(
            UpdateSimulationScenarioInput(scenario_id=scenario.id, name="renamed")
        )


def test_list_filters_by_status() -> None:
    repo = InMemorySimulationScenarioRepository()
    create = CreateSimulationScenarioUseCase(repo)
    create.execute(_create_input(name="draft-one"))
    running = create.execute(_create_input(name="running-one"))
    repo.update(running.id, status=ScenarioStatus.RUNNING)

    only_running = ListSimulationScenariosUseCase(repo).execute(
        status=ScenarioStatus.RUNNING
    )

    assert [s.id for s in only_running] == [running.id]


def test_delete_rejects_a_running_scenario() -> None:
    repo = InMemorySimulationScenarioRepository()
    scenario = CreateSimulationScenarioUseCase(repo).execute(_create_input())
    repo.update(scenario.id, status=ScenarioStatus.RUNNING)

    with pytest.raises(ValueError):
        DeleteSimulationScenarioUseCase(repo).execute(scenario.id)


def test_start_dispatches_and_sets_started_at_once() -> None:
    repo = InMemorySimulationScenarioRepository()
    dispatcher = RecordingSimulationDispatcher()
    scenario = CreateSimulationScenarioUseCase(repo).execute(_create_input())

    started = StartSimulationUseCase(repo, dispatcher).execute(scenario.id)
    assert started.status == ScenarioStatus.RUNNING
    assert started.started_at is not None
    assert dispatcher.dispatched == [scenario.id]

    # Pausing and starting again must not reset started_at (offset math
    # stays continuous across a pause/resume cycle).
    PauseSimulationUseCase(repo).execute(scenario.id)
    resumed = StartSimulationUseCase(repo, dispatcher).execute(scenario.id)
    assert resumed.started_at == started.started_at
    assert dispatcher.dispatched == [scenario.id, scenario.id]


def test_start_rejects_a_completed_scenario() -> None:
    repo = InMemorySimulationScenarioRepository()
    dispatcher = RecordingSimulationDispatcher()
    scenario = CreateSimulationScenarioUseCase(repo).execute(_create_input())
    repo.update(scenario.id, status=ScenarioStatus.COMPLETED)

    with pytest.raises(ValueError):
        StartSimulationUseCase(repo, dispatcher).execute(scenario.id)


def test_pause_is_a_noop_on_a_non_running_scenario() -> None:
    repo = InMemorySimulationScenarioRepository()
    scenario = CreateSimulationScenarioUseCase(repo).execute(_create_input())

    paused = PauseSimulationUseCase(repo).execute(scenario.id)

    assert paused.status == ScenarioStatus.DRAFT


def test_stop_is_terminal() -> None:
    repo = InMemorySimulationScenarioRepository()
    dispatcher = RecordingSimulationDispatcher()
    scenario = CreateSimulationScenarioUseCase(repo).execute(_create_input())
    StartSimulationUseCase(repo, dispatcher).execute(scenario.id)

    stopped = StopSimulationUseCase(repo).execute(scenario.id)
    assert stopped.status == ScenarioStatus.COMPLETED

    with pytest.raises(ValueError):
        StartSimulationUseCase(repo, dispatcher).execute(scenario.id)


def test_record_tick_result_accumulates_progress_and_completes_on_exhaustion() -> None:
    repo = InMemorySimulationScenarioRepository()
    dispatcher = RecordingSimulationDispatcher()
    scenario = CreateSimulationScenarioUseCase(repo).execute(_create_input())
    StartSimulationUseCase(repo, dispatcher).execute(scenario.id)
    record_tick = RecordTickResultUseCase(repo)

    mid_tick = record_tick.execute(
        scenario.id,
        events_generated=5,
        tick_offset_seconds=30,
        schedule_exhausted=False,
    )
    assert mid_tick.status == ScenarioStatus.RUNNING
    assert mid_tick.events_emitted == 5

    final_tick = record_tick.execute(
        scenario.id, events_generated=3, tick_offset_seconds=60, schedule_exhausted=True
    )
    assert final_tick.status == ScenarioStatus.COMPLETED
    assert final_tick.events_emitted == 8


def test_record_failure_marks_scenario_failed_with_error() -> None:
    repo = InMemorySimulationScenarioRepository()
    dispatcher = RecordingSimulationDispatcher()
    scenario = CreateSimulationScenarioUseCase(repo).execute(_create_input())
    StartSimulationUseCase(repo, dispatcher).execute(scenario.id)

    failed = RecordTickResultUseCase(repo).record_failure(
        scenario.id, "LLM backend timed out"
    )

    assert failed.status == ScenarioStatus.FAILED
    assert failed.error == "LLM backend timed out"


def test_status_reflects_current_progress() -> None:
    repo = InMemorySimulationScenarioRepository()
    scenario = CreateSimulationScenarioUseCase(repo).execute(_create_input())
    repo.update(scenario.id, events_emitted=42, last_tick_offset_seconds=120)

    status = GetSimulationStatusUseCase(repo).execute(scenario.id)

    assert status.events_emitted == 42
    assert status.last_tick_offset_seconds == 120
