from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import src.infrastructure.workflows.celery.alert_review_workflow as workflow_module
import src.infrastructure.workflows.celery.history_research as history_research_module
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
    DelegatedResearchSettings,
    DetectorAdversarialConfig,
    DetectorConfig,
    GeneralSettings,
    HistoryPandasResearchConfig,
    InfraSettings,
    SegmentSettings,
    TestSettings,
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
            adversarial=AdversarialConfig(
                prompt="Cliente {customer_id}, revisa {amount}"
            ),
        ),
    )

    workflow_module._run_adversarial(_context(segment))

    assert calls[0]["extra_instructions"] == "Cliente cust-1, revisa 1200.5"


def test_run_adversarial_uses_its_own_tool_selection(monkeypatch) -> None:
    calls = _patched(monkeypatch)
    segment = SegmentSettings(
        enabled=True,
        agent=AgentSettings(
            # Classification's selection must not leak into Adversarial -
            # each step has its own "Herramientas del agente" block.
            classification=ClassificationConfig(calculator_enabled=True),
            adversarial=AdversarialConfig(
                calculator_enabled=False,
                watchlist_enabled=True,
                watchlist_ids=["wl-1"],
                watchlist_compare_field="customer_id",
            ),
        ),
    )

    workflow_module._run_adversarial(_context(segment))

    assert calls[0]["enabled_tools"] == {"check_watchlist"}
    assert calls[0]["watchlist_ids"] == ["wl-1"]


def test_run_detector_adversarial_uses_its_own_tool_selection(monkeypatch) -> None:
    calls = _patched(monkeypatch)
    segment = SegmentSettings(
        enabled=True,
        agent=AgentSettings(
            detector=DetectorConfig(calculator_enabled=False),
            detector_adversarial=DetectorAdversarialConfig(
                calculator_enabled=True, max_thought_iterations=7
            ),
        ),
    )
    context = _context(segment)
    context["detector"] = context["classification"]

    workflow_module._run_detector_adversarial(context)

    assert calls[0]["enabled_tools"] == {"calculator"}
    assert calls[0]["step_name"] == "detector_adversarial"
    assert calls[0]["max_iterations"] == 7


class ChallengingAdversarialReviewAlertUseCase:
    """First review challenges the result; the re-run after research doesn't."""

    def __init__(self, inputs: list[Any]) -> None:
        self._inputs = inputs

    def execute(self, input):
        self._inputs.append(input)
        return AdversarialReviewAlertOutput(
            requires_classification_feedback=len(self._inputs) == 1,
            feedback="el monto no cuadra con el historial",
            reasoning="",
        )


def test_run_adversarial_runs_history_analysis_when_it_challenges(monkeypatch) -> None:
    calls: list[dict[str, Any]] = []
    inputs: list[Any] = []

    def fake_get_adversarial_review_alert_use_case(**kwargs):
        calls.append(kwargs)
        return ChallengingAdversarialReviewAlertUseCase(inputs)

    monkeypatch.setattr(
        workflow_module,
        "get_adversarial_review_alert_use_case",
        fake_get_adversarial_review_alert_use_case,
    )
    monkeypatch.setattr(
        history_research_module,
        "_history_research",
        lambda context, cfg, reasoning: [
            {"source": "history_pandas", "reasoning": reasoning}
        ],
    )
    segment = SegmentSettings(
        enabled=True,
        agent=AgentSettings(
            adversarial=AdversarialConfig(
                delegated_research=DelegatedResearchSettings(
                    history_pandas=HistoryPandasResearchConfig(enabled=True)
                )
            )
        ),
    )

    output = workflow_module._run_adversarial(_context(segment))

    assert len(calls) == 2
    assert "análisis de historial" in calls[1]["extra_instructions"]
    assert output.requires_classification_feedback is False
    assert output.research_delegations == [
        {"source": "history_pandas", "reasoning": "el monto no cuadra con el historial"}
    ]


def test_run_adversarial_adds_xgboost_output_as_separate_evidence(monkeypatch) -> None:
    calls = _patched(monkeypatch)
    score = workflow_module._XGBoostScore(
        score=0.9,
        model_id="model-1",
        model_tag="v1",
        is_fraud="fraud",
        verdict="superó el umbral de fraude",
        fraud_threshold=0.8,
        uncertainty_threshold=0.4,
        top_features=[{"feature": "amount", "contribution": 0.3, "value": "5000"}],
    )
    monkeypatch.setattr(
        workflow_module, "_score_with_xgboost", lambda context, cfg: score
    )
    segment = SegmentSettings(
        enabled=True,
        agent=AgentSettings(adversarial=AdversarialConfig(use_xgboost_model=True)),
    )

    output = workflow_module._run_adversarial(_context(segment))

    # Evidence only: the review still runs and decides.
    assert len(calls) == 1
    assert "Salida del modelo XGBoost" in calls[0]["extra_instructions"]
    assert '"feature": "amount"' in calls[0]["extra_instructions"]
    assert output.model_output["score"] == 0.9
    assert output.model_output["top_features"][0]["feature"] == "amount"
