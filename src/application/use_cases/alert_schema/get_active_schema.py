from src.application.ports.alert_schema_port import AlertSchemaRepository, AlertSchemaVersion


class GetActiveAlertSchemaUseCase:
    def __init__(self, repository: AlertSchemaRepository) -> None:
        self._repository = repository

    def execute(self) -> AlertSchemaVersion | None:
        return self._repository.get_active()
