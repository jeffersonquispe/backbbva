from datetime import UTC, datetime
from uuid import uuid4

from src.application.dtos.alert_schema_dtos import CreateAlertSchemaSuggestionInput
from src.application.ports.alert_schema_port import (
    AlertSchemaSuggestion,
    AlertSchemaSuggestionRepository,
)


class CreateAlertSchemaSuggestionUseCase:
    def __init__(self, repository: AlertSchemaSuggestionRepository) -> None:
        self._repository = repository

    def execute(self, input: CreateAlertSchemaSuggestionInput) -> AlertSchemaSuggestion:
        return self._repository.create(
            AlertSchemaSuggestion(
                str(uuid4()),
                input.alert_id,
                input.field,
                input.location,
                input.comment,
                input.created_by,
                datetime.now(UTC),
            )
        )


class ListAlertSchemaSuggestionsUseCase:
    def __init__(self, repository: AlertSchemaSuggestionRepository) -> None:
        self._repository = repository

    def execute(self) -> list[AlertSchemaSuggestion]:
        return self._repository.list()
