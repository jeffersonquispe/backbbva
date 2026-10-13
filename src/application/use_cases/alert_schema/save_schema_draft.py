from src.application.dtos.alert_schema_dtos import SaveAlertSchemaDraftInput
from src.application.ports.alert_schema_port import (
    AlertSchemaRepository,
    AlertSchemaVersion,
    validate_schema,
)


class SchemaVersionConflictError(ValueError):
    pass


class SaveAlertSchemaDraftUseCase:
    def __init__(self, repository: AlertSchemaRepository) -> None:
        self._repository = repository

    def execute(self, input: SaveAlertSchemaDraftInput) -> AlertSchemaVersion:
        active = self._repository.get_active()
        if input.based_on_version is not None and (active is None or active.version != input.based_on_version):
            raise SchemaVersionConflictError("Schema draft is based on a stale version")
        version = input.version
        if version is None:
            version = max((item.version for item in self._repository.list_versions()), default=0) + 1
        schema = AlertSchemaVersion(version=version, fields=input.fields, field_roles=input.field_roles, based_on_version=input.based_on_version)
        validate_schema(schema)
        existing = self._repository.get(version)
        return self._repository.update(schema) if existing else self._repository.save_draft(schema)
