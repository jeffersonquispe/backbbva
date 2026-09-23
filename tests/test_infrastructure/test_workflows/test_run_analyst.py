from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import src.infrastructure.workflows.celery.alert_review_workflow as workflow_module
from src.application.dtos.analyst_review_alert_dtos import AnalystReviewAlertOutput
from src.application.dtos.classify_alert_dtos import ClassifyAlertOutput
from src.application.dtos.pre_process_dtos import PreProcessAlertOutput
from src.application.dtos.profile_alert_dtos import ProfileAlertOutput
from src.application.ports.configuration_port import (
    AgentSettings,
    AnalystConfig,
    AnalystPlaybook,
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


class RecordingAnalystReviewAlertUseCase:
    def execute(self, input):
        return AnalystReviewAlertOutput(decision="scale_to_analyst", reasoning="", playbook_title="")


def _patched(monkeypatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def fake_get_analyst_review_alert_use_case(**kwargs):
        calls.append(kwargs)
        return RecordingAnalystReviewAlertUseCase()

    monkeypatch.setattr(
        workflow_module,
        "get_analyst_review_alert_use_case",
        fake_get_analyst_review_alert_use_case,
    )
    return calls


def test_run_analyst_passes_segment_playbooks_and_classification_vector_store(
    monkeypatch,
) -> None:
    calls = _patched(monkeypatch)
    playbook = AnalystPlaybook(id="pb-1", name="Vishing", modus_operandi_id="mo-1")
    segment = SegmentSettings(
        enabled=True,
        agent=AgentSettings(
            classification=ClassificationConfig(
                vector_store_enabled=True, vector_store_instance_id="vs-1"
            ),
            analyst=AnalystConfig(playbooks=[playbook]),
        ),
    )

    workflow_module._run_analyst(_context(segment))

    assert calls[0]["playbooks"] == [playbook]
    assert calls[0]["vector_store_instance_id"] == "vs-1"


def test_run_analyst_passes_none_vector_store_when_classification_has_none(
    monkeypatch,
) -> None:
    calls = _patched(monkeypatch)
    segment = SegmentSettings(enabled=True, agent=AgentSettings())

    workflow_module._run_analyst(_context(segment))

    assert calls[0]["playbooks"] == []
    assert calls[0]["vector_store_instance_id"] is None


def test_run_analyst_omits_segment_kwargs_without_an_active_segment(monkeypatch) -> None:
    calls = _patched(monkeypatch)
    context = _context(SegmentSettings(enabled=True, agent=AgentSettings()))
    context["segment_code"] = "unknown-segment"

    workflow_module._run_analyst(context)

    assert "playbooks" not in calls[0]
    assert "vector_store_instance_id" not in calls[0]
