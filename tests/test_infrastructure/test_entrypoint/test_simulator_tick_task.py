from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest

from src.application.dtos.simulation_dtos import GenerateEventBatchOutput
from src.application.ports.simulation_scenario_port import (
    FieldGenerator,
    GeneratorKind,
    OutputMode,
    RateInterval,
    ScenarioStatus,
    SimulationScenarioRecord,
)
from src.application.use_cases.event_simulation.record_tick_result import (
    RecordTickResultUseCase,
)
from src.infrastructure.entrypoint.simulator.celery import tasks as tasks_module


class InMemorySimulationScenarioRepository:
    def __init__(self, scenario: SimulationScenarioRecord) -> None:
        self.scenarios = {scenario.id: scenario}

    def get(self, scenario_id: UUID) -> SimulationScenarioRecord | None:
        return self.scenarios.get(scenario_id)

    def update(self, scenario_id: UUID, **changes: Any) -> SimulationScenarioRecord | None:
        current = self.scenarios.get(scenario_id)
        if current is None:
            return None
        fields = {f: getattr(current, f) for f in current.__dataclass_fields__}
        fields.update(changes)
        updated = SimulationScenarioRecord(**fields)
        self.scenarios[scenario_id] = updated
        return updated

    def create(self, scenario):
        raise NotImplementedError

    def list(self, status=None):
        raise NotImplementedError

    def delete(self, scenario_id):
        raise NotImplementedError


class StubGenerateEventBatchUseCase:
    def __init__(self, output: GenerateEventBatchOutput | Exception) -> None:
        self.output = output
        self.calls: list[Any] = []

    def execute(self, input):
        self.calls.append(input)
        if isinstance(self.output, Exception):
            raise self.output
        return self.output


class RecordingEventSink:
    def __init__(self) -> None:
        self.written: list[tuple[str, list[dict]]] = []

    def write_batch(self, dataset_name: str, rows: list[dict]) -> int:
        self.written.append((dataset_name, rows))
        return len(rows)


class RecordingAlertDispatchGateway:
    def __init__(self) -> None:
        self.dispatched: list[dict] = []

    def dispatch(self, payload: dict, *, created_by: str | None = None):
        self.dispatched.append(payload)
        return None


class RecordingApplyAsync:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def __call__(self, args=None, countdown=None, **kwargs):
        self.calls.append({"args": args, "countdown": countdown})


def _scenario(**overrides) -> SimulationScenarioRecord:
    now = datetime.now(timezone.utc)
    defaults = dict(
        id=uuid4(),
        name="scenario",
        status=ScenarioStatus.RUNNING,
        output_mode=OutputMode.DATASET,
        rate_schedule=[RateInterval(0, 120, events_per_minute=10)],
        field_specs={"channel": FieldGenerator(kind=GeneratorKind.CONSTANT, value="app")},
        target_dataset_name="synthetic_events",
        created_at=now,
        updated_at=now,
        last_tick_offset_seconds=0,
    )
    defaults.update(overrides)
    return SimulationScenarioRecord(**defaults)


def _wire(monkeypatch, scenario, *, batch_output, event_sink=None, dispatch_gateway=None):
    repo = InMemorySimulationScenarioRepository(scenario)
    generate_batch = StubGenerateEventBatchUseCase(batch_output)
    apply_async = RecordingApplyAsync()

    monkeypatch.setattr(
        tasks_module, "get_simulation_scenario_repository", lambda: repo
    )
    monkeypatch.setattr(
        tasks_module, "get_record_tick_result_use_case", lambda: RecordTickResultUseCase(repo)
    )
    monkeypatch.setattr(
        tasks_module, "get_generate_event_batch_use_case", lambda: generate_batch
    )
    monkeypatch.setattr(tasks_module, "get_event_sink", lambda: event_sink)
    monkeypatch.setattr(tasks_module, "get_alert_dispatch_gateway", lambda: dispatch_gateway)
    monkeypatch.setattr(tasks_module.tick, "apply_async", apply_async)

    return repo, generate_batch, apply_async


def test_tick_writes_to_dataset_and_reschedules_when_not_exhausted(monkeypatch) -> None:
    scenario = _scenario()
    sink = RecordingEventSink()
    repo, generate_batch, apply_async = _wire(
        monkeypatch,
        scenario,
        batch_output=GenerateEventBatchOutput(
            rows=[{"channel": "app"}, {"channel": "app"}],
            events_generated=2,
            schedule_exhausted=False,
        ),
        event_sink=sink,
    )

    result = tasks_module.tick(str(scenario.id))

    assert sink.written == [("synthetic_events", [{"channel": "app"}, {"channel": "app"}])]
    assert repo.scenarios[scenario.id].events_emitted == 2
    assert repo.scenarios[scenario.id].last_tick_offset_seconds == 10
    assert apply_async.calls == [{"args": [str(scenario.id)], "countdown": 10}]
    assert result["rescheduled"] is True


def test_tick_completes_scenario_and_stops_rescheduling_when_exhausted(monkeypatch) -> None:
    scenario = _scenario()
    sink = RecordingEventSink()
    repo, generate_batch, apply_async = _wire(
        monkeypatch,
        scenario,
        batch_output=GenerateEventBatchOutput(
            rows=[{"channel": "app"}], events_generated=1, schedule_exhausted=True
        ),
        event_sink=sink,
    )

    result = tasks_module.tick(str(scenario.id))

    assert repo.scenarios[scenario.id].status == ScenarioStatus.COMPLETED
    assert apply_async.calls == []
    assert result["rescheduled"] is False


def test_tick_dispatches_sequentially_in_live_pipeline_mode(monkeypatch) -> None:
    scenario = _scenario(output_mode=OutputMode.LIVE_PIPELINE, target_dataset_name=None)
    dispatcher = RecordingAlertDispatchGateway()
    repo, generate_batch, apply_async = _wire(
        monkeypatch,
        scenario,
        batch_output=GenerateEventBatchOutput(
            rows=[{"channel": "app"}, {"channel": "web"}],
            events_generated=2,
            schedule_exhausted=False,
        ),
        dispatch_gateway=dispatcher,
    )

    tasks_module.tick(str(scenario.id))

    assert dispatcher.dispatched == [{"channel": "app"}, {"channel": "web"}]


def test_tick_is_a_noop_when_scenario_missing(monkeypatch) -> None:
    scenario = _scenario()
    repo, generate_batch, apply_async = _wire(
        monkeypatch,
        scenario,
        batch_output=GenerateEventBatchOutput(rows=[], events_generated=0, schedule_exhausted=False),
    )

    result = tasks_module.tick(str(uuid4()))

    assert result["rescheduled"] is False
    assert apply_async.calls == []


def test_tick_is_a_noop_when_scenario_paused(monkeypatch) -> None:
    scenario = _scenario(status=ScenarioStatus.PAUSED)
    repo, generate_batch, apply_async = _wire(
        monkeypatch,
        scenario,
        batch_output=GenerateEventBatchOutput(rows=[], events_generated=0, schedule_exhausted=False),
    )

    result = tasks_module.tick(str(scenario.id))

    assert result["rescheduled"] is False
    assert generate_batch.calls == []
    assert apply_async.calls == []


def test_tick_records_failure_and_does_not_reschedule_on_exception(monkeypatch) -> None:
    scenario = _scenario()
    repo, generate_batch, apply_async = _wire(
        monkeypatch,
        scenario,
        batch_output=RuntimeError("LLM backend timed out"),
    )

    result = tasks_module.tick(str(scenario.id))

    assert repo.scenarios[scenario.id].status == ScenarioStatus.FAILED
    assert repo.scenarios[scenario.id].error == "LLM backend timed out"
    assert apply_async.calls == []
    assert result["rescheduled"] is False
