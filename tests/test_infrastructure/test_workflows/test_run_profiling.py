from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import src.infrastructure.workflows.celery.review_intake_steps as workflow_module
from src.application.dtos.pre_process_dtos import PreProcessAlertOutput
from src.application.dtos.profile_alert_dtos import ProfileAlertOutput
from src.application.ports.configuration_port import (
    AgentSettings,
    ConfigurationRecord,
    GeneralSettings,
    InfraSettings,
    ProfilingConfig,
    ProfilingStrategy,
    ProfilingStrategyKey,
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
    }


def test_run_profiling_substitutes_base_and_enrichment_variables_into_main_prompt(
    monkeypatch,
) -> None:
    calls: list[dict[str, Any]] = []

    class RecordingProfileAlertUseCase:
        def execute(self, input):
            return ProfileAlertOutput(
                user_profile="", transaction_profile="", transactional_profile=""
            )

    def fake_get_profile_alert_use_case(**kwargs):
        calls.append(kwargs)
        return RecordingProfileAlertUseCase()

    monkeypatch.setattr(
        workflow_module, "get_profile_alert_use_case", fake_get_profile_alert_use_case
    )

    segment = SegmentSettings(
        enabled=True,
        agent=AgentSettings(
            profiling=ProfilingConfig(
                field_enrichment={
                    "schema_version": 2,
                    "mappings": {"timezone": "America/Bogota", "history": "history"},
                    "recipes": [
                        {
                            "id": "r1",
                            "name": "monto_enriquecido",
                            "enabled": True,
                            "output_type": "number",
                            "source": "current",
                            "path": "amount",
                            "missing": {"policy": "missing"},
                            "steps": [{"id": "s1", "operation": "abs"}],
                        }
                    ],
                },
                strategies=[
                    ProfilingStrategy(
                        key=ProfilingStrategyKey.USUARIO,
                        main_prompt="Cliente {customer_id}, monto original {amount}, enriquecido {monto_enriquecido}",
                    ),
                    ProfilingStrategy(key=ProfilingStrategyKey.TRANSACCION),
                    ProfilingStrategy(key=ProfilingStrategyKey.TRANSACCIONAL),
                ],
            ),
        ),
    )

    workflow_module._run_profiling(_context(segment))

    assert len(calls) == 1
    assert calls[0]["extra_instructions"] == {
        "user_profile": "Cliente cust-1, monto original 1200.5, enriquecido 1200.5"
    }


def test_run_profiling_skips_extra_instructions_when_segment_has_no_main_prompt(
    monkeypatch,
) -> None:
    calls: list[dict[str, Any]] = []

    class RecordingProfileAlertUseCase:
        def execute(self, input):
            return ProfileAlertOutput(
                user_profile="", transaction_profile="", transactional_profile=""
            )

    def fake_get_profile_alert_use_case(**kwargs):
        calls.append(kwargs)
        return RecordingProfileAlertUseCase()

    monkeypatch.setattr(
        workflow_module, "get_profile_alert_use_case", fake_get_profile_alert_use_case
    )

    segment = SegmentSettings(enabled=True, agent=AgentSettings())

    workflow_module._run_profiling(_context(segment))

    assert "extra_instructions" not in calls[0]
