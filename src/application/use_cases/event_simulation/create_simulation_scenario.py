from __future__ import annotations

from src.application.dtos.simulation_dtos import CreateSimulationScenarioInput
from src.application.ports.alert_schema_port import (
    AlertSchemaDataSource,
    AlertSchemaFieldType,
    AlertSchemaRepository,
)
from src.application.ports.clock_port import Clock
from src.application.ports.id_generator_port import IdGenerator
from src.application.ports.simulation_scenario_port import (
    FieldGenerator,
    GeneratorKind,
    OutputMode,
    ScenarioStatus,
    SimulationScenarioRecord,
    SimulationScenarioRepository,
)
from src.application.runtime_defaults import (
    DEFAULT_ID_GENERATOR,
    resolve_clock,
)


class CreateSimulationScenarioUseCase:
    def __init__(
        self,
        scenario_repository: SimulationScenarioRepository,
        schema_repository: AlertSchemaRepository | None = None,
        clock: Clock | None = None,
        id_generator: IdGenerator | None = None,
    ) -> None:
        self._scenarios = scenario_repository
        self._schema_repository = schema_repository
        self._clock = resolve_clock(clock)
        self._id_generator = id_generator or DEFAULT_ID_GENERATOR

    def execute(self, input: CreateSimulationScenarioInput) -> SimulationScenarioRecord:
        if input.output_mode == OutputMode.DATASET and not input.target_dataset_name:
            raise ValueError(
                "target_dataset_name is required when output_mode is DATASET"
            )

        now = self._clock.now()
        field_specs = input.field_specs
        if field_specs is None:
            if self._schema_repository is None:
                raise ValueError("field_specs is required when no schema is configured")
            schema = self._schema_repository.get_active()
            if schema is None:
                raise ValueError("No active alert schema is available")
            field_specs = {
                field.field_ds_loc: _default_generator(field.type)
                for field in schema.fields
                if field.data_source == AlertSchemaDataSource.ARIC
                and field.is_alert
                and not field.is_label
                and field.field_ds_loc
            }
        if not field_specs:
            raise ValueError("The active schema has no ARIC fields for simulation")

        return self._scenarios.create(
            SimulationScenarioRecord(
                id=self._id_generator.new_id(),
                name=input.name,
                status=ScenarioStatus.DRAFT,
                output_mode=input.output_mode,
                rate_schedule=input.rate_schedule,
                field_specs=field_specs,
                target_dataset_name=input.target_dataset_name,
                created_by=input.created_by,
                created_at=now,
                updated_at=now,
            )
        )


def _default_generator(field_type: AlertSchemaFieldType) -> FieldGenerator:
    if field_type == AlertSchemaFieldType.NUMBER:
        return FieldGenerator(
            kind=GeneratorKind.NORMAL, params={"mu": 0.0, "sigma": 1.0}
        )
    if field_type == AlertSchemaFieldType.BOOL:
        return FieldGenerator(
            kind=GeneratorKind.CATEGORICAL, weights={"true": 1.0, "false": 1.0}
        )
    return FieldGenerator(kind=GeneratorKind.CONSTANT, value="")
