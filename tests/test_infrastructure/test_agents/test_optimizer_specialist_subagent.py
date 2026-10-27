from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from src.application.ports.agent_prompt_port import AgentPrompt
from src.application.ports.agent_specialist_executor_port import (
    AgentSpecialistExecution,
    AgentSpecialistExecutor,
)
from src.application.ports.agent_structured_generator_port import (
    AgentStructuredGenerationInput,
)
from src.application.ports.agent_subagent_port import AgentSubagentInput
from src.application.ports.embedding_port import EmbeddingResult, EmbeddingUnitOfWork
from src.application.ports.embedding_unit_of_work_factory_port import (
    EmbeddingUnitOfWorkFactory,
)
from src.application.ports.personal_data_masker_port import (
    MaskedPersonalData,
    PersonalDataMasker,
)
from src.domain.agents.objective import AgentObjective, AgentObjectiveStatus
from src.infrastructure.agents.optimizer_specialist_subagent import (
    OptimizerSpecialistSubagent,
)
from src.infrastructure.embedding.usage_meter import (
    MeteredEmbeddingUnitOfWorkFactory,
    measure_embedding_usage,
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
    def __init__(self, result: str | list[str]) -> None:
        # A list replies one item per call, repeating the last one.
        self.results = result if isinstance(result, list) else [result]
        self.request: AgentStructuredGenerationInput | None = None
        self.requests: list[AgentStructuredGenerationInput] = []

    def generate(self, request: AgentStructuredGenerationInput) -> str:
        self.request = request
        self.requests.append(request)
        return self.results[min(len(self.requests), len(self.results)) - 1]


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


def test_specialist_uses_pinned_prompt_masks_output_and_waits_for_verification() -> (
    None
):
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
        _request(
            **{prompt.name: {"name": prompt.name, "version": "3", "hash": "sha256-v3"}}
        )
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
        _request(
            **{prompt.name: {"name": prompt.name, "version": "3", "hash": "sha256-v3"}}
        )
    )

    assert result.error_code == "GENERATION_INVALID"
    assert result.verification_status == "NOT_VERIFIED"


def test_specialist_asks_once_more_after_an_invalid_proposal() -> None:
    prompt = _prompt()
    generator = RecordingGenerator(
        [
            '{"experiment":{"parameters":{"learning_rate":0.9}},"rationale":"x"}',
            '{"experiment":{"dataset_ref":"dataset-v3",'
            '"parameters":{"learning_rate":0.1}},"rationale":"candidate"}',
        ]
    )
    specialist = OptimizerSpecialistSubagent(
        name="xgboost",
        prompt_name=prompt.name,
        prompts=InMemoryPromptRepository(prompt),
        generator=generator,
        masker=InMemoryMasker(),
    )

    result = specialist.execute(
        _request(
            **{prompt.name: {"name": prompt.name, "version": "3", "hash": "sha256-v3"}}
        )
    )

    assert result.error_code is None
    assert result.verification_status == "PENDING_VERIFICATION"
    assert len(generator.requests) == 2
    assert "no cumplió el contrato" in generator.requests[1].masked_user_message
    assert "no cumplió" not in generator.requests[0].masked_user_message


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


class InMemoryEmbeddingUnitOfWork(EmbeddingUnitOfWork):
    def embed(self, texts: list[str]) -> EmbeddingResult:
        return EmbeddingResult(vectors=[[0.1, 0.2] for _ in texts], model="m", dimensions=2)


class InMemoryEmbeddingFactory(EmbeddingUnitOfWorkFactory):
    def create(self, *, model, monitoring, operation_name) -> EmbeddingUnitOfWork:
        return InMemoryEmbeddingUnitOfWork()


class RecordingEmbeddingExecutor(AgentSpecialistExecutor):
    """Embeds through the metered factory, as the vector store specialist does
    when it builds and queries a candidate generation."""

    def __init__(self, fail: bool = False) -> None:
        self.embeddings = MeteredEmbeddingUnitOfWorkFactory(InMemoryEmbeddingFactory())
        self.fail = fail

    def context(self, request: AgentSubagentInput) -> dict[str, object]:
        return {}

    def execute(self, request, experiment) -> AgentSpecialistExecution:
        unit = self.embeddings.create(model="m", monitoring=None, operation_name="op")
        unit.embed(["abcd", "ef"])
        unit.embed(["ghi"])
        if self.fail:
            raise RuntimeError("opensearch unavailable")
        return AgentSpecialistExecution(status="PASSED", safe_metrics={"aggregate_hits": 3})


@pytest.mark.parametrize("fail", [False, True])
def test_specialist_reports_embedding_usage_of_its_execution(fail: bool) -> None:
    prompt = _prompt()
    specialist = OptimizerSpecialistSubagent(
        name="xgboost",
        prompt_name=prompt.name,
        prompts=InMemoryPromptRepository(prompt),
        generator=RecordingGenerator(
            '{"experiment":{"dataset_ref":"dataset-v3",'
            '"parameters":{"learning_rate":0.04}},"rationale":"ok"}'
        ),
        masker=InMemoryMasker(),
        executor=RecordingEmbeddingExecutor(fail=fail),
    )

    result = specialist.execute(
        _request(
            **{prompt.name: {"name": prompt.name, "version": "3", "hash": "sha256-v3"}}
        )
    )

    usage = {"embedding_calls": 2, "embedding_texts": 3, "embedding_characters": 9}
    if fail:
        assert result.error_code == "EXECUTION_FAILED"
        assert result.safe_metrics == usage
    else:
        assert result.safe_metrics == {"aggregate_hits": 3, **usage}


def test_embedding_usage_is_only_counted_inside_a_measurement() -> None:
    unit = MeteredEmbeddingUnitOfWorkFactory(InMemoryEmbeddingFactory()).create(
        model="m", monitoring=None, operation_name="op"
    )
    unit.embed(["outside"])
    with measure_embedding_usage() as usage:
        unit.embed(["inside"])
        with measure_embedding_usage() as nested:
            unit.embed(["deeper", "x"])

    assert (usage.calls, usage.texts, usage.characters) == (1, 1, 6)
    assert (nested.calls, nested.texts, nested.characters) == (1, 2, 7)
