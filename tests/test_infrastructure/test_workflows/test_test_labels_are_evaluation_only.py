from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from src.application.dtos.adversarial_review_alert_dtos import (
    AdversarialReviewAlertInput,
)
from src.application.dtos.classify_alert_dtos import (
    ClassifyAlertInput,
    ClassifyAlertOutput,
)
from src.application.dtos.pre_process_dtos import PreProcessAlertOutput
from src.application.dtos.profile_alert_dtos import ProfileAlertOutput
from src.application.ports.alert_port import AlertRecord, AlertStatus
from src.application.ports.alert_schema_port import (
    AlertSchemaDataSource,
    AlertSchemaField,
    AlertSchemaRepository,
    AlertSchemaVersion,
)
from src.application.use_cases.alerts.adversarial_review_alert import _review_context
from src.application.use_cases.alerts.classify_alert import _alert_context
from src.application.use_cases.test_runs.get_test_run import (
    _canonical_evaluation_labels,
)
from src.infrastructure.workflows.celery.alert_review_workflow import _alert_payload

LABEL_VALUE = "label-must-not-be-prompted"


def _pre_process() -> PreProcessAlertOutput:
    return PreProcessAlertOutput(
        schema_version=7,
        input={"amount": 100},
        labels={"marcacion_final": LABEL_VALUE, "tipo": "Fraude"},
    )


def _classification() -> ClassifyAlertOutput:
    return ClassifyAlertOutput(
        is_fraud="fraud",
        fraud_classification="ACCOUNT_TAKEOVER",
        reasoning="reason",
        expected_classification=LABEL_VALUE,
        ground_truth_tipo="Fraude",
    )


def test_agent_contexts_and_detector_features_exclude_canonical_labels() -> None:
    pre_process = _pre_process()
    profile = ProfileAlertOutput("", "", "")
    classification_input = ClassifyAlertInput(
        alert_id=uuid.uuid4(),
        pre_process=pre_process,
        profile=profile,
        expected_classification=LABEL_VALUE,
        ground_truth_tipo="Fraude",
    )
    adversarial_input = AdversarialReviewAlertInput(
        alert_id=classification_input.alert_id,
        pre_process=pre_process,
        profile=profile,
        classification=_classification(),
    )

    prompt_inputs = [
        _alert_context(classification_input),
        _review_context(adversarial_input),
        _alert_payload({"pre_process": pre_process}),
    ]

    assert all(LABEL_VALUE not in json.dumps(value, default=str) for value in prompt_inputs)
    assert all("Fraude" not in json.dumps(value, default=str) for value in prompt_inputs)


class InMemorySchemaRepository(AlertSchemaRepository):
    def __init__(self, schema: AlertSchemaVersion) -> None:
        self.schema = schema

    def get(self, version: int) -> AlertSchemaVersion | None:
        return self.schema if version == self.schema.version else None

    def get_active(self):
        return self.schema

    def list_versions(self):
        return [self.schema]

    def save_draft(self, schema):
        return schema

    def update(self, schema):
        return schema


class InMemoryAlertRepository:
    def __init__(self, alert: AlertRecord) -> None:
        self.alert = alert

    def get(self, alert_id):
        return self.alert if alert_id == self.alert.id else None


def test_test_run_evaluation_reads_only_schema_labels() -> None:
    alert_id = uuid.uuid4()
    now = datetime.now(UTC)
    schema = AlertSchemaVersion(
        version=7,
        fields=[
            AlertSchemaField(
                id="outcome",
                data_source=AlertSchemaDataSource.ARIC,
                field="marcacion_final",
                field_ds_loc="marcacion_final",
                is_label=True,
            ),
            AlertSchemaField(
                id="matured",
                data_source=AlertSchemaDataSource.ARIC,
                field="tipo",
                field_ds_loc="tipo",
                is_label=True,
            ),
            AlertSchemaField(
                id="noise",
                data_source=AlertSchemaDataSource.ARIC,
                field="noise",
                field_ds_loc="noise",
            ),
        ],
    )
    alert = AlertRecord(
        id=alert_id,
        event_id="event",
        event_type="payment",
        status=AlertStatus.CLOSED,
        created_at=now,
        updated_at=now,
        labels={"marcacion_final": LABEL_VALUE, "tipo": "Fraude", "noise": "ignored"},
        schema_version=7,
    )

    labels = _canonical_evaluation_labels(
        alert_id,
        InMemoryAlertRepository(alert),
        InMemorySchemaRepository(schema),
    )

    assert labels == {"marcacion_final": LABEL_VALUE, "tipo": "Fraude"}
