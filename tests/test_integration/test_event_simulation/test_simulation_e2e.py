"""End-to-end simulator check against DynamoDB Local.

The fixture mirrors only non-personal columns seen in the first rows of the
locally supplied sample CSV (event type, channel, integration point, scores
and amount).  It deliberately does not read the large CSV at test time and
does not copy customer data into the repository.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from uuid import UUID

import pytest

if not os.getenv("DYNAMO_ENDPOINT"):
    pytest.skip(
        "Requires DynamoDB Local (set DYNAMO_ENDPOINT)", allow_module_level=True
    )

from src.application.dtos.simulation_dtos import CreateSimulationScenarioInput
from src.application.ports.simulation_scenario_port import (
    FieldGenerator,
    GeneratorKind,
    OutputMode,
    RateInterval,
)
from src.application.use_cases.event_simulation.create_simulation_scenario import (
    CreateSimulationScenarioUseCase,
)
from src.application.use_cases.event_simulation.generate_event_batch import (
    GenerateEventBatchUseCase,
)
from src.application.use_cases.event_simulation.record_tick_result import (
    RecordTickResultUseCase,
)
from src.application.use_cases.event_simulation.start_simulation import (
    StartSimulationUseCase,
)
from src.infrastructure.entrypoint.simulator.celery import tasks as simulator_tasks
from src.infrastructure.persistence.database.dynamodb.repositories.simulation_scenario_repository import (
    DynamoSimulationScenarioRepository,
)
from src.infrastructure.persistence.database.dynamodb.simulator_schemas import (
    ensure_simulator_tables,
)

pytestmark = pytest.mark.docker_integration


@dataclass
class RecordingSimulationDispatcher:
    dispatched_ids: list[UUID] = field(default_factory=list)

    def dispatch(self, scenario_id: UUID) -> None:
        self.dispatched_ids.append(scenario_id)


@dataclass
class RecordingAlertDispatchGateway:
    dispatched_rows: list[dict] = field(default_factory=list)

    def dispatch(self, payload: dict, *, created_by: str | None = None) -> None:
        assert created_by == "event-simulator"
        self.dispatched_rows.append(payload)


def _sampled_field_specs() -> dict[str, FieldGenerator]:
    """A small, PII-free scenario representative of the supplied CSV."""
    return {
        "eventtype": FieldGenerator(kind=GeneratorKind.CONSTANT, value="paymentRT"),
        "channel": FieldGenerator(
            kind=GeneratorKind.CATEGORICAL, weights={"OM": 3, "GL": 1}
        ),
        "integrationpoint": FieldGenerator(
            kind=GeneratorKind.CONSTANT,
            value="SMGG20211063 - patchPaymentRequest",
        ),
        "biocatch_score": FieldGenerator(
            kind=GeneratorKind.NORMAL, params={"mu": 930, "sigma": 12}
        ),
        "Model_score": FieldGenerator(
            kind=GeneratorKind.UNIFORM, params={"low": 0.90, "high": 1.0}
        ),
        "amount_value": FieldGenerator(
            kind=GeneratorKind.LOGNORMAL, params={"mu": 16.7, "sigma": 0.15}
        ),
        "event_count": FieldGenerator(kind=GeneratorKind.POISSON, params={"lambda": 3}),
    }


def test_live_simulation_persists_generates_and_dispatches_through_one_tick(
    monkeypatch,
) -> None:
    """Exercises Dynamo persistence -> lifecycle -> tick -> live dispatch.

    The external alert API is replaced with a recorder: this proves the
    simulator contract without creating an alert or making an LLM call.
    """
    ensure_simulator_tables()
    repository = DynamoSimulationScenarioRepository()
    lifecycle_dispatcher = RecordingSimulationDispatcher()
    alert_dispatcher = RecordingAlertDispatchGateway()
    scenario = CreateSimulationScenarioUseCase(repository).execute(
        CreateSimulationScenarioInput(
            name="e2e-simulation-sampled-fields",
            output_mode=OutputMode.LIVE_PIPELINE,
            # A single ten-second tick.  The high rate makes the test
            # deterministic in practice while keeping it bounded to one tick.
            rate_schedule=[RateInterval(0, 10, events_per_minute=120)],
            field_specs=_sampled_field_specs(),
            created_by="automated-e2e",
        )
    )

    try:
        started = StartSimulationUseCase(repository, lifecycle_dispatcher).execute(
            scenario.id
        )
        assert lifecycle_dispatcher.dispatched_ids == [scenario.id]
        assert started.status.value == "RUNNING"

        monkeypatch.setattr(
            simulator_tasks, "get_simulation_scenario_repository", lambda: repository
        )
        monkeypatch.setattr(
            simulator_tasks,
            "get_record_tick_result_use_case",
            lambda: RecordTickResultUseCase(repository),
        )
        monkeypatch.setattr(
            simulator_tasks,
            "get_generate_event_batch_use_case",
            lambda: GenerateEventBatchUseCase(
                llm_unit_of_work_factory=None, monitoring=None
            ),
        )
        monkeypatch.setattr(
            simulator_tasks, "get_alert_dispatch_gateway", lambda: alert_dispatcher
        )

        result = simulator_tasks.tick(str(scenario.id))
        persisted = repository.get(scenario.id)

        assert result["rescheduled"] is False
        assert persisted is not None
        assert persisted.status.value == "COMPLETED"
        assert persisted.events_emitted == len(alert_dispatcher.dispatched_rows)
        assert persisted.events_emitted > 0
        assert persisted.last_tick_offset_seconds == 10
        for row in alert_dispatcher.dispatched_rows:
            assert row["eventtype"] == "paymentRT"
            assert row["channel"] in {"OM", "GL"}
            assert row["integrationpoint"] == "SMGG20211063 - patchPaymentRequest"
            assert 0.90 <= row["Model_score"] <= 1.0
            assert row["amount_value"] > 0
            assert row["event_count"] >= 0
    finally:
        repository.delete(scenario.id)
