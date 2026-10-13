from src.application.ports.alert_schema_port import AlertSchemaRepository, AlertSchemaVersion


class ListAlertSchemaVersionsUseCase:
    def __init__(self, repository: AlertSchemaRepository) -> None:
        self._repository = repository

    def execute(self) -> list[AlertSchemaVersion]:
        return self._repository.list_versions()


class GetAlertSchemaVersionUseCase:
    def __init__(self, repository: AlertSchemaRepository) -> None:
        self._repository = repository

    def execute(self, version: int) -> AlertSchemaVersion | None:
        return self._repository.get(version)
