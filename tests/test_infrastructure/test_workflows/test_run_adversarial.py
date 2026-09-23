from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import src.infrastructure.workflows.celery.alert_review_workflow as workflow_module
from src.application.dtos.adversarial_review_alert_dtos import (
    AdversarialReviewAlertOutput,
)
from src.application.dtos.classify_alert_dtos import ClassifyAlertOutput
from src.application.dtos.pre_process_dtos import PreProcessAlertOutput
from src.application.dtos.profile_alert_dtos import ProfileAlertOutput
from src.application.ports.configuration_port import (
    AdversarialConfig,
    AgentSettings,
    ClassificationConfig,
    ConfigurationRecord,
    GeneralSettings,
    InfraSettings,
    OpsSettings,
    SegmentSettings,
    TestSettings,
)


def _config_with_segment(segment: SegmentSettings) -> ConfigurationRecord:
    now = datetime.now(timezone.utc)
    return ConfigurationRecord(
        configuration_id="cfg-1",
        version=1,
        name="cfg-1-v1",
        description="",
        active=True,
        general=GeneralSettings(),
        infra=InfraSettings(),
        ops=OpsSettings(),
        test=TestSettings(),
        created_at=now,
        updated_at=now,
        segments={"tarjetas": segment},
    )


def _context(segment: SegmentSettings) -> dict[str, Any]:
    return {
        "alert_id": "00000000-0000-0000-0000-000000000001",
        "active_configuration": _config_with_segment(segment),
        "segment_code": "tarjetas",
        "input": {},
        "pre_process": PreProcessAlertOutput(
            mandatory_fields={"customer_id": "cust-1"},
            optional_fields={"amount": 1200.5},
            enrichment={
                "aric_signals": None,
                "customer_profile": None,
                "transaction_history": [],
                "personal_data_changes": [],
            },
            pre_process_note="",
        ),
        "profiling": ProfileAlertOutput(
            user_profile="", transaction_profile="", transactional_profile=""
        ),
        "classification": ClassifyAlertOutput(
            is_fraud="fraud", fraud_classification="ACCOUNT_TAKEOVER", reasoning=""
        ),
    }


class RecordingAdversarialReviewAlertUseCase:
    def execute(self, input):
        return AdversarialReviewAlertOutput(
            requires_classification_feedback=False, feedback="", reasoning=""
        )


def _patched(monkeypatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def fake_get_adversarial_review_alert_use_case(**kwargs):
        calls.append(kwargs)
        return RecordingAdversarialReviewAlertUseCase()

    monkeypatch.setattr(
        workflow_module,
        "get_adversarial_review_alert_use_case",
        fake_get_adversarial_review_alert_use_case,
    )
    return calls


def test_run_adversarial_substitutes_variables_into_prompt(monkeypatch) -> None:
    calls = _patched(monkeypatch)
    segment = SegmentSettings(
        enabled=True,
        agent=AgentSettings(
            adversarial=AdversarialConfig(prompt="Cliente {customer_id}, revisa {amount}"),
        ),
    )

    workflow_module._run_adversarial(_context(segment))

    assert calls[0]["extra_instructions"] == "Cliente cust-1, revisa 1200.5"


def test_run_adversarial_reuses_classification_tool_selection(monkeypatch) -> None:
    calls = _patched(monkeypatch)
    segment = SegmentSettings(
        enabled=True,
        agent=AgentSettings(
            classification=ClassificationConfig(
                vector_store_enabled=True,
                vector_store_instance_id="vs-1",
                calculator_enabled=True,
            ),
            # Adversarial's own switches are ignored by design (see
            # alert_review_workflow.py's _run_adversarial comment) - only
            # Classification's selection above should reach enabled_tools.
            adversarial=AdversarialConfig(calculator_enabled=False),
        ),
    )

    workflow_module._run_adversarial(_context(segment))

    assert "calculator" in calls[0]["enabled_tools"]
    assert "get_similar_frauds" in calls[0]["enabled_tools"]
    assert calls[0]["vector_store_instance_id"] == "vs-1"


def test_run_adversarial_disables_fraud_knowledge_tools_without_a_vector_store(
    monkeypatch,
) -> None:
    # vector_store_enabled alone isn't enough - a real vector_store_instance_id
    # must be picked too, otherwise get_*_port() in factories.py would fall
    # back to the Mock adapter and silently return fake results.
    calls = _patched(monkeypatch)
    segment = SegmentSettings(
        enabled=True,
        agent=AgentSettings(
            classification=ClassificationConfig(vector_store_enabled=True),
        ),
    )

    workflow_module._run_adversarial(_context(segment))

    assert "get_similar_frauds" not in calls[0]["enabled_tools"]
    assert "vector_store_instance_id" not in calls[0]
