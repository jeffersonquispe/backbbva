from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import src.infrastructure.workflows.celery.factories as factories
import src.infrastructure.workflows.celery.review_agent_steps as workflow_module
from src.application.dtos.classify_alert_dtos import ClassifyAlertOutput
from src.application.dtos.pre_process_dtos import PreProcessAlertOutput
from src.application.dtos.profile_alert_dtos import ProfileAlertOutput
from src.application.use_cases.research.research_tool import BoundedResearchTool
from src.domain.configurations.entities import (
    AgentSettings,
    ClassificationConfig,
    ConfigurationRecord,
    DelegatedResearchSettings,
    GeneralSettings,
    InfraSettings,
    SegmentSettings,
    TestSettings,
    VectorStoreResearchConfig,
)


def _config_with_segment(segment: SegmentSettings) -> ConfigurationRecord:
    now = datetime.now(UTC)
    return ConfigurationRecord(
        configuration_id="cfg-1",
        version=1,
        name="cfg-1-v1",
        description="",
        active=True,
        general=GeneralSettings(),
        infra=InfraSettings(),
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
            optional_fields={"amount": 1200.5, "documento": "12345678"},
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
    }


class RecordingClassifyAlertUseCase:
    def execute(self, input):
        return ClassifyAlertOutput(
            is_fraud="unknown", fraud_classification="unknown", reasoning=""
        )


def _patched(monkeypatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def fake_get_classify_alert_use_case(**kwargs):
        calls.append(kwargs)
        return RecordingClassifyAlertUseCase()

    monkeypatch.setattr(
        workflow_module, "get_classify_alert_use_case", fake_get_classify_alert_use_case
    )
    return calls


def test_run_classification_substitutes_variables_into_prompt(monkeypatch) -> None:
    calls = _patched(monkeypatch)
    segment = SegmentSettings(
        enabled=True,
        agent=AgentSettings(
            classification=ClassificationConfig(
                prompt="Cliente {customer_id}, monto {amount}",
            )
        ),
    )

    workflow_module._run_classification(_context(segment))

    assert calls[0]["extra_instructions"] == "Cliente cust-1, monto 1200.5"


def test_run_classification_passes_calculator_and_output_labels_and_max_iterations(
    monkeypatch,
) -> None:
    calls = _patched(monkeypatch)
    segment = SegmentSettings(
        enabled=True,
        agent=AgentSettings(
            classification=ClassificationConfig(
                calculator_enabled=True,
                output_labels=["ACCOUNT_TAKEOVER", "CARD_NOT_PRESENT"],
                max_thought_iterations=3,
            )
        ),
    )

    workflow_module._run_classification(_context(segment))

    assert "calculator" in calls[0]["enabled_tools"]
    assert calls[0]["output_labels"] == ["ACCOUNT_TAKEOVER", "CARD_NOT_PRESENT"]
    assert calls[0]["max_iterations"] == 3


def _vector_store_segment(instance_id: str | None) -> SegmentSettings:
    return SegmentSettings(
        enabled=True,
        agent=AgentSettings(
            classification=ClassificationConfig(
                delegated_research=DelegatedResearchSettings(
                    vector_store=VectorStoreResearchConfig(
                        enabled=True,
                        vector_store_instance_id=instance_id,
                        max_delegations=2,
                    )
                )
            )
        ),
    )


def test_run_classification_exposes_vector_store_research_as_a_bounded_tool(
    monkeypatch,
) -> None:
    calls = _patched(monkeypatch)
    monkeypatch.setattr(
        factories, "get_search_fraud_knowledge_use_case", lambda: object()
    )

    workflow_module._run_classification(_context(_vector_store_segment("vs-1")))

    research_tool = calls[0]["vector_store_research"]
    assert isinstance(research_tool, BoundedResearchTool)
    assert research_tool.remaining == 2
    # "Base de conocimiento" direct tools are gone - the research tool replaces them.
    assert "get_similar_frauds" not in calls[0]["enabled_tools"]


def test_run_classification_omits_vector_store_research_without_an_instance_id(
    monkeypatch,
) -> None:
    calls = _patched(monkeypatch)

    workflow_module._run_classification(_context(_vector_store_segment(None)))

    assert "vector_store_research" not in calls[0]


def test_run_classification_passes_watchlist_config_only_when_fully_set(
    monkeypatch,
) -> None:
    calls = _patched(monkeypatch)
    segment = SegmentSettings(
        enabled=True,
        agent=AgentSettings(
            classification=ClassificationConfig(
                watchlist_enabled=True,
                watchlist_ids=["wl-1"],
                watchlist_compare_field="documento",
            )
        ),
    )

    workflow_module._run_classification(_context(segment))

    assert "check_watchlist" in calls[0]["enabled_tools"]
    assert calls[0]["watchlist_ids"] == ["wl-1"]
    assert calls[0]["watchlist_compare_field"] == "documento"


def test_run_classification_omits_watchlist_kwargs_when_compare_field_missing(
    monkeypatch,
) -> None:
    calls = _patched(monkeypatch)
    segment = SegmentSettings(
        enabled=True,
        agent=AgentSettings(
            classification=ClassificationConfig(
                watchlist_enabled=True,
                watchlist_ids=["wl-1"],
                watchlist_compare_field=None,
            )
        ),
    )

    workflow_module._run_classification(_context(segment))

    assert "check_watchlist" not in calls[0]["enabled_tools"]
    assert "watchlist_ids" not in calls[0]
