from __future__ import annotations

import random

import pytest

from src.application.dtos.simulation_dtos import GenerateEventBatchInput
from src.application.ports.llm_unit_of_work_port import (
    LLMInvocationResult,
    LLMMessage,
    LLMUnitOfWork,
    LLMUnitOfWorkFactory,
)
from src.application.ports.simulation_scenario_port import (
    FieldGenerator,
    GeneratorKind,
    OutputMode,
    RateInterval,
    ScenarioStatus,
    SimulationScenarioRecord,
)
from src.application.use_cases.event_simulation.generate_event_batch import (
    GenerateEventBatchUseCase,
)
from datetime import datetime, timezone
import uuid


class RecordingLLMUnitOfWork(LLMUnitOfWork):
    def __init__(self, response: str) -> None:
        self.response = response
        self.received_prompts: list[str] = []

    def invoke(self, messages: list[LLMMessage]) -> LLMInvocationResult:
        self.received_prompts.append(messages[-1].content)
        return LLMInvocationResult(content=self.response, model="fake-model")


class RecordingLLMUnitOfWorkFactory(LLMUnitOfWorkFactory):
    def __init__(self, response: str = "generated text") -> None:
        self.response = response
        self.created: list[RecordingLLMUnitOfWork] = []

    def create(self, *, model, monitoring, operation_name, temperature=0.0, max_tokens=None):
        uow = RecordingLLMUnitOfWork(self.response)
        self.created.append(uow)
        return uow


class StubDatasetReaderGateway:
    def __init__(self, row: dict | None) -> None:
        self.row = row
        self.requested_datasets: list[str] = []

    def sample_row(self, dataset_name: str, rng: random.Random) -> dict | None:
        self.requested_datasets.append(dataset_name)
        return self.row


def _scenario(field_specs: dict[str, FieldGenerator], rate_schedule: list[RateInterval]) -> SimulationScenarioRecord:
    now = datetime.now(timezone.utc)
    return SimulationScenarioRecord(
        id=uuid.uuid4(),
        name="scenario",
        status=ScenarioStatus.RUNNING,
        output_mode=OutputMode.DATASET,
        rate_schedule=rate_schedule,
        field_specs=field_specs,
        target_dataset_name="synthetic_events",
        created_at=now,
        updated_at=now,
    )


def test_generates_structured_fields_without_any_llm_dependency() -> None:
    scenario = _scenario(
        field_specs={"channel": FieldGenerator(kind=GeneratorKind.CONSTANT, value="app")},
        rate_schedule=[RateInterval(0, 60, events_per_minute=60)],
    )
    use_case = GenerateEventBatchUseCase(llm_unit_of_work_factory=None, monitoring=None)

    output = use_case.execute(
        GenerateEventBatchInput(
            scenario=scenario, window_start_seconds=0, window_end_seconds=60, max_events=100, seed=1
        )
    )

    assert output.events_generated == len(output.rows)
    assert all(row == {"channel": "app"} for row in output.rows)
    assert output.schedule_exhausted is True


def test_max_events_caps_a_high_rate_window() -> None:
    scenario = _scenario(
        field_specs={"channel": FieldGenerator(kind=GeneratorKind.CONSTANT, value="app")},
        rate_schedule=[RateInterval(0, 60, events_per_minute=6000)],
    )
    use_case = GenerateEventBatchUseCase(llm_unit_of_work_factory=None, monitoring=None)

    output = use_case.execute(
        GenerateEventBatchInput(
            scenario=scenario, window_start_seconds=0, window_end_seconds=60, max_events=5, seed=1
        )
    )

    assert output.events_generated <= 5


def test_template_llm_field_substitutes_earlier_fields_into_the_prompt() -> None:
    scenario = _scenario(
        field_specs={
            "customer_id": FieldGenerator(kind=GeneratorKind.CONSTANT, value="cust-1"),
            "narrative": FieldGenerator(
                kind=GeneratorKind.TEMPLATE_LLM,
                system_prompt="You write fraud alert narratives.",
                user_prompt_template="Write a narrative for customer {customer_id}.",
                model="gpt-x",
            ),
        },
        rate_schedule=[RateInterval(0, 60, events_per_minute=60)],
    )
    llm_factory = RecordingLLMUnitOfWorkFactory(response="synthetic narrative")
    use_case = GenerateEventBatchUseCase(llm_unit_of_work_factory=llm_factory, monitoring=object())

    output = use_case.execute(
        GenerateEventBatchInput(
            scenario=scenario, window_start_seconds=0, window_end_seconds=60, max_events=100, seed=3
        )
    )

    assert output.events_generated > 0
    for row in output.rows:
        assert row["narrative"] == "synthetic narrative"
    assert "Write a narrative for customer cust-1." in llm_factory.created[0].received_prompts


def test_generate_preview_ignores_rate_schedule_and_returns_exact_count() -> None:
    use_case = GenerateEventBatchUseCase(llm_unit_of_work_factory=None, monitoring=None)
    field_specs = {"channel": FieldGenerator(kind=GeneratorKind.CONSTANT, value="app")}

    rows = use_case.generate_preview(field_specs, count=5, seed=1)

    assert rows == [{"channel": "app"}] * 5


def test_template_llm_field_without_llm_factory_raises() -> None:
    scenario = _scenario(
        field_specs={
            "narrative": FieldGenerator(
                kind=GeneratorKind.TEMPLATE_LLM,
                system_prompt="sys",
                user_prompt_template="prompt",
            ),
        },
        rate_schedule=[RateInterval(0, 60, events_per_minute=6000)],
    )
    use_case = GenerateEventBatchUseCase(llm_unit_of_work_factory=None, monitoring=None)

    with pytest.raises(ValueError):
        use_case.execute(
            GenerateEventBatchInput(
                scenario=scenario, window_start_seconds=0, window_end_seconds=60, max_events=10, seed=1
            )
        )


def test_seed_recreation_field_pulls_a_real_row_and_rewrites_it() -> None:
    scenario = _scenario(
        field_specs={
            "description": FieldGenerator(
                kind=GeneratorKind.SEED_RECREATION,
                system_prompt="Rewrite the given text with different entities.",
                user_prompt_template="Rewrite: {seed_value}",
                model="gpt-x",
                seed_dataset_name="real_alerts",
                seed_field="description",
            ),
        },
        rate_schedule=[RateInterval(0, 60, events_per_minute=6000)],
    )
    llm_factory = RecordingLLMUnitOfWorkFactory(response="rewritten description")
    dataset_reader = StubDatasetReaderGateway(row={"description": "original text"})
    use_case = GenerateEventBatchUseCase(
        llm_unit_of_work_factory=llm_factory,
        monitoring=object(),
        dataset_reader=dataset_reader,
    )

    output = use_case.execute(
        GenerateEventBatchInput(
            scenario=scenario, window_start_seconds=0, window_end_seconds=60, max_events=1, seed=5
        )
    )

    assert dataset_reader.requested_datasets == ["real_alerts"] * output.events_generated
    for row in output.rows:
        assert row["description"] == "rewritten description"
    if output.events_generated:
        assert "Rewrite: original text" in llm_factory.created[0].received_prompts


def test_seed_recreation_field_without_dataset_reader_raises() -> None:
    scenario = _scenario(
        field_specs={
            "description": FieldGenerator(
                kind=GeneratorKind.SEED_RECREATION,
                system_prompt="sys",
                user_prompt_template="{seed_value}",
                seed_dataset_name="real_alerts",
                seed_field="description",
            ),
        },
        rate_schedule=[RateInterval(0, 60, events_per_minute=6000)],
    )
    llm_factory = RecordingLLMUnitOfWorkFactory()
    use_case = GenerateEventBatchUseCase(
        llm_unit_of_work_factory=llm_factory, monitoring=object(), dataset_reader=None
    )

    with pytest.raises(ValueError):
        use_case.execute(
            GenerateEventBatchInput(
                scenario=scenario, window_start_seconds=0, window_end_seconds=60, max_events=1, seed=1
            )
        )
