from src.application.dtos.alert_schema_dtos import ApproveAlertSchemaInput
from src.application.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from src.application.ports.alert_schema_port import (
    AlertSchemaRepository,
    AlertSchemaStatus,
    AlertSchemaVersion,
)
from src.application.ports.clock_port import Clock
from src.application.runtime_defaults import resolve_clock


class SelfApprovalError(ForbiddenError):
    pass


class ImpactAcknowledgementRequired(ValidationError):
    pass


class ApproveAlertSchemaUseCase:
    def __init__(
        self, repository: AlertSchemaRepository, clock: Clock | None = None
    ) -> None:
        self._repository = repository
        self._clock = resolve_clock(clock)

    def execute(self, input: ApproveAlertSchemaInput) -> AlertSchemaVersion:
        schema = self._repository.get(input.version)
        if schema is None:
            raise NotFoundError("Alert schema version not found")
        if schema.status != AlertSchemaStatus.PROPOSED:
            raise ConflictError("Only proposed schemas can be approved")
        if schema.proposed_by == input.approver_id:
            raise SelfApprovalError("A user cannot approve their own proposal")
        active = self._repository.get_active()
        if active is not None and schema.based_on_version != active.version:
            raise ConflictError("Schema proposal is based on a stale version")
        if schema.impact and not input.impact_acknowledged:
            raise ImpactAcknowledgementRequired("Impact acknowledgement is required")
        approved = AlertSchemaVersion(
            **{
                **schema.__dict__,
                "status": AlertSchemaStatus.ACTIVE,
                "approved_by": input.approver_id,
                "approved_at": self._clock.now(),
                "impact_acknowledged": bool(schema.impact)
                and input.impact_acknowledged,
            }
        )
        if active is not None:
            self._repository.update(
                AlertSchemaVersion(
                    **{**active.__dict__, "status": AlertSchemaStatus.HISTORICAL}
                )
            )
        return self._repository.update(approved)
