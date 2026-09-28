from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.dtos.simulation_dtos import (
    CreateSimulationScenarioInput,
    SimulationStatusOutput,
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
from src.infrastructure.entrypoint.api.factories.simulation_scenario_factory import (
    get_create_simulation_scenario_use_case,
    get_delete_simulation_scenario_use_case,
    get_generate_event_batch_use_case,
    get_get_simulation_scenario_use_case,
    get_get_simulation_status_use_case,
    get_list_simulation_scenarios_use_case,
    get_pause_simulation_use_case,
    get_start_simulation_use_case,
    get_stop_simulation_use_case,
    get_update_simulation_scenario_use_case,
)
from src.infrastructure.entrypoint.api.routers.scenarios_router import router


def _scenario(**overrides) -> SimulationScenarioRecord:
    now = datetime.now(timezone.utc)
    defaults = dict(
        id=uuid4(),
        name="scenario",
        status=ScenarioStatus.DRAFT,
        output_mode=OutputMode.DATASET,
        rate_schedule=[RateInterval(0, 60, events_per_minute=10)],
        field_specs={"channel": FieldGenerator(kind=GeneratorKind.CONSTANT, value="app")},
        target_dataset_name="synthetic_events",
        created_by="tester",
        created_at=now,
        updated_at=now,
    )
    defaults.update(overrides)
    return SimulationScenarioRecord(**defaults)


class FakeCreateUseCase:
    def __init__(self, result: SimulationScenarioRecord | Exception) -> None:
        self.result = result

    def execute(self, input: CreateSimulationScenarioInput) -> SimulationScenarioRecord:
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeGetUseCase:
    def __init__(self, result: SimulationScenarioRecord | None) -> None:
        self.result = result

    def execute(self, scenario_id: UUID) -> SimulationScenarioRecord | None:
        return self.result


class FakeListUseCase:
    def __init__(self, results: list[SimulationScenarioRecord]) -> None:
        self.results = results

    def execute(self, status=None) -> list[SimulationScenarioRecord]:
        return self.results


class FakeUpdateUseCase:
    def __init__(self, result: SimulationScenarioRecord | Exception) -> None:
        self.result = result

    def execute(self, input: UpdateSimulationScenarioInput) -> SimulationScenarioRecord:
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeDeleteUseCase:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.deleted: UUID | None = None

    def execute(self, scenario_id: UUID) -> None:
        if self.error:
            raise self.error
        self.deleted = scenario_id


class FakeLifecycleUseCase:
    def __init__(self, result: SimulationScenarioRecord | Exception) -> None:
        self.result = result

    def execute(self, scenario_id: UUID) -> SimulationScenarioRecord:
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeStatusUseCase:
    def __init__(self, result: SimulationStatusOutput | Exception) -> None:
        self.result = result

    def execute(self, scenario_id: UUID) -> SimulationStatusOutput:
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeGenerateBatchUseCase:
    def generate_preview(self, field_specs, count, seed=None) -> list[dict]:
        return [{"channel": "app"} for _ in range(count)]


def _client(overrides: dict | None = None) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    defaults = {
        get_create_simulation_scenario_use_case: lambda: FakeCreateUseCase(_scenario()),
        get_get_simulation_scenario_use_case: lambda: FakeGetUseCase(None),
        get_list_simulation_scenarios_use_case: lambda: FakeListUseCase([]),
        get_update_simulation_scenario_use_case: lambda: FakeUpdateUseCase(_scenario()),
        get_delete_simulation_scenario_use_case: lambda: FakeDeleteUseCase(),
        get_start_simulation_use_case: lambda: FakeLifecycleUseCase(_scenario()),
        get_pause_simulation_use_case: lambda: FakeLifecycleUseCase(_scenario()),
        get_stop_simulation_use_case: lambda: FakeLifecycleUseCase(_scenario()),
        get_get_simulation_status_use_case: lambda: FakeStatusUseCase(
            SimulationStatusOutput(
                scenario_id=uuid4(),
                status=ScenarioStatus.RUNNING,
                events_emitted=0,
                last_tick_offset_seconds=0,
                error=None,
            )
        ),
        get_generate_event_batch_use_case: lambda: FakeGenerateBatchUseCase(),
    }
    defaults.update(overrides or {})
    app.dependency_overrides.update(defaults)
    return TestClient(app)


_CREATE_PAYLOAD = {
    "name": "scenario",
    "output_mode": "DATASET",
    "rate_schedule": [
        {"start_offset_seconds": 0, "end_offset_seconds": 60, "events_per_minute": 10}
    ],
    "field_specs": {
        "channel": {"kind": "CONSTANT", "value": "app"},
    },
    "target_dataset_name": "synthetic_events",
}


def test_create_scenario_returns_201_with_body() -> None:
    scenario = _scenario(name="my-scenario")
    response = _client(
        {get_create_simulation_scenario_use_case: lambda: FakeCreateUseCase(scenario)}
    ).post("/scenarios", json=_CREATE_PAYLOAD)

    assert response.status_code == 201
    body = response.json()
    assert body["id"] == str(scenario.id)
    assert body["name"] == "my-scenario"
    assert body["field_specs"]["channel"]["kind"] == "CONSTANT"


def test_create_scenario_maps_value_error_to_400() -> None:
    response = _client(
        {
            get_create_simulation_scenario_use_case: lambda: FakeCreateUseCase(
                ValueError("target_dataset_name is required")
            )
        }
    ).post("/scenarios", json=_CREATE_PAYLOAD)

    assert response.status_code == 400


def test_get_scenario_returns_404_when_missing() -> None:
    response = _client().get(f"/scenarios/{uuid4()}")
    assert response.status_code == 404


def test_get_scenario_returns_scenario_when_found() -> None:
    scenario = _scenario()
    response = _client(
        {get_get_simulation_scenario_use_case: lambda: FakeGetUseCase(scenario)}
    ).get(f"/scenarios/{scenario.id}")

    assert response.status_code == 200
    assert response.json()["id"] == str(scenario.id)


def test_list_scenarios_returns_all_results() -> None:
    scenarios = [_scenario(name="a"), _scenario(name="b")]
    response = _client(
        {get_list_simulation_scenarios_use_case: lambda: FakeListUseCase(scenarios)}
    ).get("/scenarios")

    assert response.status_code == 200
    names = {row["name"] for row in response.json()}
    assert names == {"a", "b"}


def test_update_scenario_maps_lookup_error_to_404() -> None:
    response = _client(
        {
            get_update_simulation_scenario_use_case: lambda: FakeUpdateUseCase(
                LookupError("not found")
            )
        }
    ).put(f"/scenarios/{uuid4()}", json={"name": "renamed"})

    assert response.status_code == 404


def test_update_scenario_maps_value_error_to_400() -> None:
    response = _client(
        {
            get_update_simulation_scenario_use_case: lambda: FakeUpdateUseCase(
                ValueError("Cannot edit a RUNNING scenario")
            )
        }
    ).put(f"/scenarios/{uuid4()}", json={"name": "renamed"})

    assert response.status_code == 400


def test_delete_scenario_returns_204() -> None:
    fake = FakeDeleteUseCase()
    scenario_id = uuid4()
    response = _client({get_delete_simulation_scenario_use_case: lambda: fake}).delete(
        f"/scenarios/{scenario_id}"
    )

    assert response.status_code == 204
    assert fake.deleted == scenario_id


def test_delete_scenario_maps_value_error_to_400() -> None:
    response = _client(
        {
            get_delete_simulation_scenario_use_case: lambda: FakeDeleteUseCase(
                ValueError("Cannot delete a RUNNING scenario")
            )
        }
    ).delete(f"/scenarios/{uuid4()}")

    assert response.status_code == 400


def test_start_pause_stop_return_updated_scenario() -> None:
    running = _scenario(status=ScenarioStatus.RUNNING)
    client = _client(
        {
            get_start_simulation_use_case: lambda: FakeLifecycleUseCase(running),
            get_pause_simulation_use_case: lambda: FakeLifecycleUseCase(running),
            get_stop_simulation_use_case: lambda: FakeLifecycleUseCase(running),
        }
    )

    for action in ("start", "pause", "stop"):
        response = client.post(f"/scenarios/{running.id}/{action}")
        assert response.status_code == 200
        assert response.json()["status"] == "RUNNING"


def test_start_scenario_maps_lookup_error_to_404() -> None:
    response = _client(
        {
            get_start_simulation_use_case: lambda: FakeLifecycleUseCase(
                LookupError("not found")
            )
        }
    ).post(f"/scenarios/{uuid4()}/start")

    assert response.status_code == 404


def test_get_scenario_status_returns_progress() -> None:
    scenario_id = uuid4()
    status_output = SimulationStatusOutput(
        scenario_id=scenario_id,
        status=ScenarioStatus.RUNNING,
        events_emitted=42,
        last_tick_offset_seconds=120,
        error=None,
    )
    response = _client(
        {get_get_simulation_status_use_case: lambda: FakeStatusUseCase(status_output)}
    ).get(f"/scenarios/{scenario_id}/status")

    assert response.status_code == 200
    body = response.json()
    assert body["events_emitted"] == 42
    assert body["last_tick_offset_seconds"] == 120


def test_preview_scenario_returns_generated_rows_without_persisting() -> None:
    scenario = _scenario()
    response = _client(
        {get_get_simulation_scenario_use_case: lambda: FakeGetUseCase(scenario)}
    ).post(f"/scenarios/{scenario.id}/preview", params={"count": 3})

    assert response.status_code == 200
    assert response.json() == [{"channel": "app"}] * 3


def test_preview_scenario_returns_404_when_scenario_missing() -> None:
    response = _client().post(f"/scenarios/{uuid4()}/preview")
    assert response.status_code == 404
