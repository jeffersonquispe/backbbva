from src.application.dtos.alert_schema_dtos import CreateAlertSchemaSuggestionInput
from src.application.ports.alert_schema_port import (
    AlertSchemaSuggestion,
    AlertSchemaSuggestionRepository,
)
from src.application.ports.clock_port import Clock
from src.application.ports.id_generator_port import IdGenerator
from src.application.runtime_defaults import (
    DEFAULT_ID_GENERATOR,
    resolve_clock,
)


class CreateAlertSchemaSuggestionUseCase:
    def __init__(
        self,
        repository: AlertSchemaSuggestionRepository,
        clock: Clock | None = None,
        id_generator: IdGenerator | None = None,
    ) -> None:
        self._repository = repository
        self._clock = resolve_clock(clock)
        self._id_generator = id_generator or DEFAULT_ID_GENERATOR

    def execute(self, input: CreateAlertSchemaSuggestionInput) -> AlertSchemaSuggestion:
        return self._repository.create(
            AlertSchemaSuggestion(
                str(self._id_generator.new_id()),
                input.alert_id,
                input.field,
                input.location,
                input.comment,
                input.created_by,
                self._clock.now(),
            )
        )


class ListAlertSchemaSuggestionsUseCase:
    def __init__(self, repository: AlertSchemaSuggestionRepository) -> None:
        self._repository = repository

    def execute(self) -> list[AlertSchemaSuggestion]:
        return self._repository.list()
