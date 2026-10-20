from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from src.application.ports.agent_prompt_port import AgentPrompt
from src.application.ports.agent_structured_generator_port import (
    AgentStructuredGenerationInput,
)
from src.application.ports.agent_subagent_port import AgentSubagentInput
from src.application.ports.personal_data_masker_port import (
    MaskedPersonalData,
    PersonalDataMasker,
)
from src.domain.agents.objective import AgentObjective, AgentObjectiveStatus
from src.infrastructure.agents.optimizer_specialist_subagent import (
    OptimizerSpecialistSubagent,
)


class InMemoryPromptRepository:
    def __init__(self, prompt: AgentPrompt) -> None:
        self.prompt = prompt

    def get_version(self, name: str, version: int) -> AgentPrompt | None:
        if (name, version) == (self.prompt.name, self.prompt.version):
            return self.prompt
        return None

    def create_version(self, prompt):
        self.prompt = prompt
        return prompt

    def get_active(self, name):
        return None

    def activate(self, pointer, expected_version):
        return None


class RecordingGenerator:
    def __init__(self, result: str) -> None:
        self.result = result
        self.request: AgentStructuredGenerationInput | None = None

    def generate(self, request: AgentStructuredGenerationInput) -> str:
        self.request = request
        return self.result


class InMemoryMasker(PersonalDataMasker):
    def mask(self, text: str) -> MaskedPersonalData:
        return MaskedPersonalData(text.replace("3001234567", "[CELULAR]"), {})


def _prompt() -> AgentPrompt:
    return AgentPrompt(
        name="agent.specialist.xgboost",
        version=3,
        content="prompt de prueba",
        content_hash="sha256-v3",
        status="ACTIVE",
        created_at=datetime(2026, 10, 20, tzinfo=UTC),
    )


def _request(**prompt_versions) -> AgentSubagentInput:
    return AgentSubagentInput(
        session_id="session-safe",
        iteration_number=4,
        scope={"areas": ["model"], "customer_id": "avoidance-customer-1"},
        hypothesis="Mejorar recall usando 3001234567 como ejemplo",
        budget={"tokens": 100},
        prompt_versions=prompt_versions,
    )


def test_specialist_uses_pinned_prompt_masks_output_and_waits_for_verification() -> None:
    prompt = _prompt()
    generator = RecordingGenerator(
        '{"experiment":{"dataset_ref":"dataset-v3",'
        '"parameters":{"learning_rate":0.04}},'
        '"rationale":"Revisar 3001234567 como ejemplo"}'
    )
    specialist = OptimizerSpecialistSubagent(
        name="xgboost",
        prompt_name=prompt.name,
        prompts=InMemoryPromptRepository(prompt),
        generator=generator,
        masker=InMemoryMasker(),
    )

    result = specialist.execute(
        _request(**{prompt.name: {"name": prompt.name, "version": "3", "hash": "sha256-v3"}})
    )

    assert generator.request is not None
    assert generator.request.system_prompt == prompt.content
    assert generator.request.masked_user_message.endswith("[CELULAR] como ejemplo")
    assert "customer_id" not in generator.request.persisted_context
    assert "avoidance-customer-1" not in generator.request.persisted_context
    assert result.contribution["rationale"] == "Revisar [CELULAR] como ejemplo"
    assert result.verification_status == "PENDING_VERIFICATION"
    assert result.safe_metrics == {"proposal_fields": 2}


def test_specialist_rejects_prompt_version_that_differs_from_session_pin() -> None:
    prompt = _prompt()
    specialist = OptimizerSpecialistSubagent(
        name="xgboost",
        prompt_name=prompt.name,
        prompts=InMemoryPromptRepository(prompt),
        generator=RecordingGenerator('{"experiment":{"depth":4},"rationale":"ok"}'),
        masker=InMemoryMasker(),
    )

    result = specialist.execute(
        _request(**{prompt.name: {"name": prompt.name, "version": "2", "hash": "old"}})
    )

    assert result.error_code == "PROMPT_VERSION_MISMATCH"
    assert result.contribution == {}


def test_specialist_serializes_dynamodb_decimal_in_pinned_objective_context() -> None:
    prompt = _prompt()
    generator = RecordingGenerator(
        '{"experiment":{"dataset_ref":"authorized-v3",'
        '"parameters":{"max_depth":4}},"rationale":"Parámetros acotados"}'
    )
    specialist = OptimizerSpecialistSubagent(
        name="xgboost",
        prompt_name=prompt.name,
        prompts=InMemoryPromptRepository(prompt),
        generator=generator,
        masker=InMemoryMasker(),
    )
    objective = AgentObjective(
        objective_id="global",
        version=2,
        success_label="label",
        positive_label="fraud",
        negative_label="legitimate",
        maturing_days=7,
        expected_coverage_pct=Decimal("97.5"),  # type: ignore[arg-type]
        stable_months=3,
        primary_metrics=("precision", "recall"),
        precision_floor=Decimal("0.91"),  # type: ignore[arg-type]
        minimum_support_per_segment=20,
        minimum_global_support=30,
        minimum_count_to_publish_aggregates=30,
        minimum_mature_alert_coverage_pct=Decimal("80"),  # type: ignore[arg-type]
        unlabeled_rule="exclude",
        schema_mapping={"nested": {"threshold": Decimal("0.25")}},
        status=AgentObjectiveStatus.ACTIVE,
        created_by="manager",
        created_at=datetime(2026, 10, 20, tzinfo=UTC),
    )
    request = replace(
        _request(
            **{
                prompt.name: {
                    "name": prompt.name,
                    "version": "3",
                    "hash": prompt.content_hash,
                }
            }
        ),
        objective=objective,
    )

    result = specialist.execute(request)

    assert result.error_code is None
    assert result.verification_status == "PENDING_VERIFICATION"
    assert generator.request is not None
    context = json.loads(generator.request.persisted_context)
    assert context["objective"]["precision_floor"] == 0.91
    assert context["objective"]["schema_mapping"]["nested"]["threshold"] == 0.25


def test_xgboost_specialist_rejects_parameters_outside_approved_bounds() -> None:
    prompt = _prompt()
    specialist = OptimizerSpecialistSubagent(
        name="xgboost",
        prompt_name=prompt.name,
        prompts=InMemoryPromptRepository(prompt),
        generator=RecordingGenerator(
            '{"experiment":{"dataset_ref":"dataset-v3",'
            '"parameters":{"learning_rate":0.9}},"rationale":"candidate"}'
        ),
        masker=InMemoryMasker(),
    )

    result = specialist.execute(
        _request(**{prompt.name: {"name": prompt.name, "version": "3", "hash": "sha256-v3"}})
    )

    assert result.error_code == "GENERATION_INVALID"
    assert result.verification_status == "NOT_VERIFIED"


@pytest.mark.parametrize(
    ("name", "experiment"),
    [
        (
            "configuration",
            {"changes": [{"path": "segments.digital.threshold", "value": 0.4}]},
        ),
        (
            "library",
            {
                "entity_type": "modus_operandi",
                "draft": {"title": "Patrón agregado"},
                "evidence_summary": "Señales agregadas",
            },
        ),
        (
            "vector_store",
            {"manifest_version": 7, "authorized_queries": ["patrón A"]},
        ),
        (
            "xgboost",
            {
                "dataset_ref": "dataset-v3",
                "parameters": {"n_estimators": 250, "max_depth": 4},
            },
        ),
    ],
)
def test_specialists_validate_their_candidate_shape_before_evaluation(
    name: str, experiment: dict[str, object]
) -> None:
    prompt = AgentPrompt(
        name=f"agent.specialist.{name}",
        version=3,
        content="prompt",
        content_hash="pinned-hash",
        status="ACTIVE",
        created_at=datetime(2026, 10, 20, tzinfo=UTC),
    )
    specialist = OptimizerSpecialistSubagent(
        name=name,
        prompt_name=prompt.name,
        prompts=InMemoryPromptRepository(prompt),
        generator=RecordingGenerator(
            json.dumps({"experiment": experiment, "rationale": "Prueba agregada"})
        ),
        masker=InMemoryMasker(),
    )

    result = specialist.execute(
        _request(
            **{
                prompt.name: {
                    "name": prompt.name,
                    "version": "3",
                    "hash": "pinned-hash",
                }
            }
        )
    )

    assert result.error_code is None
    assert result.verification_status == "PENDING_VERIFICATION"
