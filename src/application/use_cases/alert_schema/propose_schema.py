from src.application.errors import ConflictError, NotFoundError
from src.application.ports.alert_schema_port import (
    AlertSchemaRepository,
    AlertSchemaStatus,
    AlertSchemaVersion,
)
from src.application.ports.clock_port import Clock
from src.application.runtime_defaults import resolve_clock
from src.application.use_cases.alert_schema.helpers import compare_schema


class ProposeAlertSchemaUseCase:
    def __init__(
        self,
        repository: AlertSchemaRepository,
        impact_analyzer,
        clock: Clock | None = None,
    ) -> None:
        self._repository, self._impact_analyzer = repository, impact_analyzer
        self._clock = resolve_clock(clock)

    def execute(self, version: int, user_id: str) -> AlertSchemaVersion:
        schema = self._repository.get(version)
        if schema is None:
            raise NotFoundError("Alert schema version not found")
        if schema.status != AlertSchemaStatus.DRAFT:
            raise ConflictError("Only drafts can be proposed")
        active = self._repository.get_active()
        comparison = compare_schema(schema, active)
        impact = self._impact_analyzer(comparison)
        proposed = AlertSchemaVersion(
            **{
                **schema.__dict__,
                "status": AlertSchemaStatus.PROPOSED,
                "proposed_by": user_id,
                "proposed_at": self._clock.now(),
                "comparison": comparison.as_dict(),
                "impact": impact,
            }
        )
        return self._repository.update(proposed)
