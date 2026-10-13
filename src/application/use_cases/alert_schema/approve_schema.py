from datetime import datetime, timezone

from src.application.dtos.alert_schema_dtos import ApproveAlertSchemaInput
from src.application.ports.alert_schema_port import AlertSchemaRepository, AlertSchemaStatus, AlertSchemaVersion


class SelfApprovalError(PermissionError):
    pass


class ImpactAcknowledgementRequired(ValueError):
    pass


class ApproveAlertSchemaUseCase:
    def __init__(self, repository: AlertSchemaRepository) -> None:
        self._repository = repository

    def execute(self, input: ApproveAlertSchemaInput) -> AlertSchemaVersion:
        schema = self._repository.get(input.version)
        if schema is None:
            raise LookupError("Alert schema version not found")
        if schema.status != AlertSchemaStatus.PROPOSED:
            raise ValueError("Only proposed schemas can be approved")
        if schema.proposed_by == input.approver_id:
            raise SelfApprovalError("A user cannot approve their own proposal")
        active = self._repository.get_active()
        if active is not None and schema.based_on_version != active.version:
            raise ValueError("Schema proposal is based on a stale version")
        if schema.impact and not input.impact_acknowledged:
            raise ImpactAcknowledgementRequired("Impact acknowledgement is required")
        approved = AlertSchemaVersion(**{**schema.__dict__, "status": AlertSchemaStatus.ACTIVE,
            "approved_by": input.approver_id, "approved_at": datetime.now(timezone.utc),
            "impact_acknowledged": bool(schema.impact) and input.impact_acknowledged})
        if active is not None:
            self._repository.update(AlertSchemaVersion(**{**active.__dict__, "status": AlertSchemaStatus.HISTORICAL}))
        return self._repository.update(approved)
