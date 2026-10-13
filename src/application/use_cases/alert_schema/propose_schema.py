from datetime import UTC, datetime

from src.application.ports.alert_schema_port import (
    AlertSchemaRepository,
    AlertSchemaStatus,
    AlertSchemaVersion,
)
from src.application.use_cases.alert_schema.helpers import compare_schema


class ProposeAlertSchemaUseCase:
    def __init__(self, repository: AlertSchemaRepository, impact_analyzer) -> None:
        self._repository, self._impact_analyzer = repository, impact_analyzer

    def execute(self, version: int, user_id: str) -> AlertSchemaVersion:
        schema = self._repository.get(version)
        if schema is None:
            raise LookupError("Alert schema version not found")
        if schema.status != AlertSchemaStatus.DRAFT:
            raise ValueError("Only drafts can be proposed")
        active = self._repository.get_active()
        comparison = compare_schema(schema, active)
        impact = self._impact_analyzer(comparison)
        proposed = AlertSchemaVersion(**{**schema.__dict__, "status": AlertSchemaStatus.PROPOSED,
            "proposed_by": user_id, "proposed_at": datetime.now(UTC),
            "comparison": comparison.as_dict(), "impact": impact})
        return self._repository.update(proposed)
