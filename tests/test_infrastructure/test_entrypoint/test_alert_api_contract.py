from datetime import UTC, datetime
from uuid import uuid4

from src.infrastructure.entrypoint.api.schemas.alert_schemas import (
    AlertSchemaFieldSchema,
    AlertSchemaVersionResponse,
)
from src.infrastructure.entrypoint.api.schemas.operations import AlertDetailResponse


def test_alert_response_contract_keeps_dynamic_fields_extensible() -> None:
    alert_id = uuid4()
    response = AlertDetailResponse.model_validate(
        {
            "alert_id": alert_id,
            "event_id": "evt-1",
            "event_type": "payment",
            "status": "CLOSED",
            "customer_id": None,
            "created_at": datetime(2026, 10, 25, tzinfo=UTC),
            "schema_version": 12,
            "configuration_ref": None,
            "input": {"counterparty_alias": "merchant", "new_numeric_field": 0.75},
            "labels": {"review_outcome": "fraud"},
            "history_prev_alerta": [],
            "agent_output": {},
            "reservation": None,
            "analyst_resolution": None,
            "workflow_execution_id": None,
            "workflow_status": None,
            "workflow_output": None,
            "steps": [],
        }
    )

    assert response.alert_id == alert_id
    assert response.schema_version == 12
    assert response.input["new_numeric_field"] == 0.75
    assert response.labels["review_outcome"] == "fraud"


def test_schema_contract_carries_version_and_configurable_field_names() -> None:
    schema = AlertSchemaVersionResponse.model_validate(
        {
            "version": 12,
            "status": "active",
            "fields": [
                {
                    "id": "counterparty",
                    "data_source": "aric",
                    "field": "counterparty_alias",
                    "field_name": "Counterparty",
                    "field_ds_loc": "payment.merchant.name",
                    "type": "string",
                    "is_alert": True,
                    "is_mandatory": False,
                    "is_history": False,
                    "is_core": False,
                    "is_label": False,
                    "is_sensible": False,
                    "sensitivity_strategy": None,
                    "group": "transaction",
                    "description": "",
                    "use_locale": False,
                    "locale_type": None,
                }
            ],
            "field_roles": {},
            "proposed_by": None,
            "proposed_at": None,
            "approved_by": None,
            "approved_at": None,
            "impact_acknowledged": False,
            "based_on_version": None,
            "comparison": {},
            "impact": [],
        }
    )

    field: AlertSchemaFieldSchema = schema.fields[0]
    assert schema.version == 12
    assert field.field == "counterparty_alias"
