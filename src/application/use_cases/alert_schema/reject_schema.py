from src.application.ports.alert_schema_port import (
    AlertSchemaRepository,
    AlertSchemaStatus,
    AlertSchemaVersion,
)


class RejectAlertSchemaUseCase:
    def __init__(self, repository: AlertSchemaRepository) -> None:
        self._repository = repository

    def execute(self, version: int) -> AlertSchemaVersion:
        schema = self._repository.get(version)
        if schema is None:
            raise LookupError("Alert schema version not found")
        if schema.status != AlertSchemaStatus.PROPOSED:
            raise ValueError("Only proposed schemas can be rejected")
        return self._repository.update(AlertSchemaVersion(**{**schema.__dict__, "status": AlertSchemaStatus.REJECTED}))
