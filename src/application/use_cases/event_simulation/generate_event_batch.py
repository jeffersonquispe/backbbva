from __future__ import annotations

import random

from src.application.dtos.simulation_dtos import (
    GenerateEventBatchInput,
    GenerateEventBatchOutput,
)
from src.application.errors import ValidationError
from src.application.ports.dataset_reader_gateway_port import DatasetReaderGateway
from src.application.ports.llm_unit_of_work_factory_port import LLMUnitOfWorkFactory
from src.application.ports.llm_unit_of_work_port import LLMMessage, LLMMessageRole
from src.application.ports.monitoring_port import MonitoringPort
from src.application.ports.simulation_scenario_port import FieldGenerator, GeneratorKind
from src.application.use_cases.event_simulation.field_generation import (
    STRUCTURED_KINDS,
    draw_structured_value,
    due_event_count,
    schedule_exhausted,
)
from src.domain.models.prompt_template import substitute_variables

_DEFAULT_MODEL = ""  # empty -> LLMUnitOfWorkFactory's own default model choice


class GenerateEventBatchUseCase:
    """The event simulator's core generation logic - framework-free besides
    the two ports it needs for unstructured/recreated fields. Structured
    fields (CONSTANT/CATEGORICAL/UNIFORM/NORMAL/LOGNORMAL/POISSON) never
    touch either port, so a scenario with no TEMPLATE_LLM/SEED_RECREATION
    field can be exercised with llm_unit_of_work_factory=None."""

    def __init__(
        self,
        llm_unit_of_work_factory: LLMUnitOfWorkFactory | None,
        monitoring: MonitoringPort | None,
        dataset_reader: DatasetReaderGateway | None = None,
    ) -> None:
        self._llm_factory = llm_unit_of_work_factory
        self._monitoring = monitoring
        self._dataset_reader = dataset_reader

    def execute(self, input: GenerateEventBatchInput) -> GenerateEventBatchOutput:
        rng = random.Random(input.seed)
        count = due_event_count(
            input.scenario.rate_schedule,
            input.window_start_seconds,
            input.window_end_seconds,
            rng,
        )
        count = min(count, input.max_events)

        rows = [
            self._generate_one(input.scenario.field_specs, rng) for _ in range(count)
        ]

        return GenerateEventBatchOutput(
            rows=rows,
            events_generated=len(rows),
            schedule_exhausted=schedule_exhausted(
                input.scenario.rate_schedule, input.window_end_seconds
            ),
        )

    def generate_preview(
        self,
        field_specs: dict[str, FieldGenerator],
        count: int,
        seed: int | None = None,
    ) -> list[dict]:
        """Draws `count` fully-resolved rows ignoring the rate schedule
        entirely - backs the API's /preview endpoint, so an admin can see
        what a scenario's LLM-generated fields actually look like before
        starting it, without waiting for the tick loop."""
        rng = random.Random(seed)
        return [self._generate_one(field_specs, rng) for _ in range(count)]

    def _generate_one(
        self, field_specs: dict[str, FieldGenerator], rng: random.Random
    ) -> dict:
        # Fields are resolved in field_specs' own (insertion) order, so a
        # TEMPLATE_LLM/SEED_RECREATION prompt can only reference fields
        # defined earlier in the scenario - documented on FieldGenerator's
        # user_prompt_template field.
        row: dict = {}
        for field_name, generator in field_specs.items():
            if generator.kind in STRUCTURED_KINDS:
                _set_payload_value(
                    row, field_name, draw_structured_value(generator, rng)
                )
            elif generator.kind == GeneratorKind.TEMPLATE_LLM:
                _set_payload_value(
                    row, field_name, self._generate_llm_text(generator, row)
                )
            elif generator.kind == GeneratorKind.SEED_RECREATION:
                _set_payload_value(
                    row, field_name, self._recreate_seed_field(generator, row, rng)
                )
            else:
                raise ValidationError(f"Unknown generator kind: {generator.kind}")
        return row

    def _generate_llm_text(self, generator: FieldGenerator, row: dict) -> str:
        if self._llm_factory is None or self._monitoring is None:
            raise ValidationError(
                "TEMPLATE_LLM field requires an LLMUnitOfWorkFactory + MonitoringPort"
            )
        prompt = substitute_variables(generator.user_prompt_template or "", row)
        return self._invoke_llm(generator, prompt)

    def _recreate_seed_field(
        self, generator: FieldGenerator, row: dict, rng: random.Random
    ) -> str | None:
        if self._llm_factory is None or self._monitoring is None:
            raise ValidationError(
                "SEED_RECREATION field requires an LLMUnitOfWorkFactory + MonitoringPort"
            )
        if self._dataset_reader is None:
            raise ValidationError("SEED_RECREATION field requires a DatasetReaderGateway")
        if not generator.seed_dataset_name or not generator.seed_field:
            raise ValidationError(
                "SEED_RECREATION field requires seed_dataset_name and seed_field"
            )
        seed_row = self._dataset_reader.sample_row(generator.seed_dataset_name, rng)
        seed_value = (seed_row or {}).get(generator.seed_field)
        prompt_variables = {**row, "seed_value": seed_value}
        prompt = substitute_variables(
            generator.user_prompt_template or "", prompt_variables
        )
        return self._invoke_llm(generator, prompt)

    def _invoke_llm(self, generator: FieldGenerator, prompt: str) -> str:
        if self._llm_factory is None or self._monitoring is None:
            raise ValidationError(
                "LLM field requires an LLMUnitOfWorkFactory + MonitoringPort"
            )
        uow = self._llm_factory.create(
            model=generator.model or _DEFAULT_MODEL,
            monitoring=self._monitoring,
            operation_name="event_simulation.generate_field",
            temperature=generator.temperature,
        )
        result = uow.invoke(
            [
                LLMMessage(
                    role=LLMMessageRole.SYSTEM,
                    content=generator.system_prompt or "",
                ),
                LLMMessage(role=LLMMessageRole.USER, content=prompt),
            ]
        )
        return result.content


def _set_payload_value(row: dict, location: str, value) -> None:
    """Use schema locations as dotted payload paths; flat names stay flat."""
    if "." not in location:
        row[location] = value
        return
    current = row
    parts = location.split(".")
    for part in parts[:-1]:
        current = current.setdefault(part, {})
    current[parts[-1]] = value
