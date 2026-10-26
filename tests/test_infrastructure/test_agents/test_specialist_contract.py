"""Contract every optimizer specialist must honour, run against all of them.

A new specialist only has to be added to `SPECIALISTS`; the same battery then
proves it never raises, never leaks raw text and only emits catalogued codes.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from src.application.ports.agent_prompt_port import AgentPrompt
from src.application.ports.agent_specialist_executor_port import (
    AgentSpecialistExecution,
)
from src.application.ports.agent_subagent_port import AgentSubagentInput
from src.application.ports.personal_data_masker_port import (
    MaskedPersonalData,
    PersonalDataMasker,
)
from src.application.use_cases.agent.orchestrate_agent_iteration import (
    _SAFE_AUDIT_REASONS,
)
from src.domain.agents.failure_catalog import CATALOG
from src.infrastructure.agents.optimizer_specialist_subagent import (
    OptimizerSpecialistSubagent,
)

# name -> a valid experiment proposal for that specialist.
SPECIALISTS: dict[str, dict[str, object]] = {
    "configuration": {"changes": [{"path": "pipeline.threshold", "value": 0.5}]},
    "library": {
        "entity_type": "taxonomy",
        "draft": {"name": "Nueva"},
        "evidence_summary": "resumen agregado",
    },
    "vector_store": {"manifest_version": 2, "authorized_queries": ["consulta"]},
    "xgboost": {"parameters": {"learning_rate": 0.05}},
}
EMAIL = "ana.perez@banco.com"


class Prompts:
    def __init__(self, prompt: AgentPrompt | None) -> None:
        self.prompt = prompt

    def get_version(self, name, version):
        return self.prompt


class Generator:
    def __init__(self, result: str | None = None, error: Exception | None = None):
        self.result, self.error = result, error
        self.seen: list[object] = []

    def generate(self, request):
        self.seen.append(request)
        if self.error is not None:
            raise self.error
        return self.result


class EmailMasker(PersonalDataMasker):
    def mask(self, text: str) -> MaskedPersonalData:
        found = {"email": 1} if EMAIL in text else {}
        return MaskedPersonalData(text.replace(EMAIL, "[EMAIL]"), found)


class Executor:
    def __init__(self, context_error=None, execute_error=None, execution=None):
        self.context_error = context_error
        self.execute_error = execute_error
        self.execution = execution or AgentSpecialistExecution(
            status="PASSED", safe_metrics={"precision": 0.9, "recall": 0.6}
        )

    def context(self, request):
        if self.context_error:
            raise self.context_error
        return {"note": f"contexto {EMAIL}"}

    def execute(self, request, experiment):
        if self.execute_error:
            raise self.execute_error
        return self.execution


def _prompt(name: str) -> AgentPrompt:
    return AgentPrompt(
        name=name,
        version=1,
        content="prompt",
        content_hash="h1",
        status="ACTIVE",
        created_at=datetime(2026, 10, 26, tzinfo=UTC),
    )


def _request(
    name: str, *, pinned: bool = True, hash_: str = "h1"
) -> AgentSubagentInput:
    prompt_name = f"agent.specialist.{name}"
    return AgentSubagentInput(
        session_id="s1",
        iteration_number=1,
        scope={"areas": [name], "note": f"contacto {EMAIL}"},
        hypothesis=f"Probar mejora; contacto {EMAIL}",
        budget={"tokens": 10},
        prompt_versions=(
            {prompt_name: {"name": prompt_name, "version": "1", "hash": hash_}}
            if pinned
            else {}
        ),
    )


def _specialist(name, *, generator, executor=None, prompt="present"):
    prompt_name = f"agent.specialist.{name}"
    return OptimizerSpecialistSubagent(
        name=name,
        prompt_name=prompt_name,
        prompts=Prompts(_prompt(prompt_name) if prompt == "present" else None),
        generator=generator,
        masker=EmailMasker(),
        executor=executor,
    )


def _valid(name: str) -> str:
    return json.dumps({"experiment": SPECIALISTS[name], "rationale": "porque sí"})


def _assert_catalogued(output) -> None:
    assert output.error_code in CATALOG, output.error_code


@pytest.mark.parametrize("name", SPECIALISTS)
def test_every_specialist_returns_its_own_name(name) -> None:
    output = _specialist(name, generator=Generator(_valid(name))).execute(
        _request(name)
    )

    assert output.subagent == name
    assert output.error_code is None
    assert output.verification_status == "PENDING_VERIFICATION"


@pytest.mark.parametrize("name", SPECIALISTS)
@pytest.mark.parametrize(
    "error", [RuntimeError("boom"), ValueError("bad"), TypeError("t")]
)
def test_generation_errors_become_a_catalogued_code(name, error) -> None:
    output = _specialist(name, generator=Generator(error=error)).execute(_request(name))

    assert output.error_code == "GENERATION_FAILED"
    _assert_catalogued(output)


@pytest.mark.parametrize("name", SPECIALISTS)
@pytest.mark.parametrize(
    "raw",
    ["no es json", "[]", '{"experiment": 1}', '{"experiment": {}, "rationale": "x"}'],
)
def test_malformed_proposals_are_invalid_not_exceptions(name, raw) -> None:
    output = _specialist(name, generator=Generator(raw)).execute(_request(name))

    assert output.error_code == "GENERATION_INVALID"
    _assert_catalogued(output)


@pytest.mark.parametrize("name", SPECIALISTS)
def test_prompt_pinning_failures_are_catalogued(name) -> None:
    generator = Generator(_valid(name))
    cases = [
        (
            _specialist(name, generator=generator),
            _request(name, pinned=False),
            "PROMPT_NOT_PINNED",
        ),
        (
            _specialist(name, generator=generator, prompt="missing"),
            _request(name),
            "PROMPT_VERSION_MISMATCH",
        ),
        (
            _specialist(name, generator=generator),
            _request(name, hash_="other"),
            "PROMPT_VERSION_MISMATCH",
        ),
    ]
    for specialist, request, expected in cases:
        output = specialist.execute(request)
        assert output.error_code == expected
        _assert_catalogued(output)
    assert generator.seen == []


@pytest.mark.parametrize("name", SPECIALISTS)
def test_executor_failures_never_leak_the_raw_error(name) -> None:
    context_failure = _specialist(
        name,
        generator=Generator(_valid(name)),
        executor=Executor(context_error=RuntimeError(f"db down for {EMAIL}")),
    ).execute(_request(name))
    execution_failure = _specialist(
        name,
        generator=Generator(_valid(name)),
        executor=Executor(execute_error=ValueError(f"row 77 of {EMAIL}")),
    ).execute(_request(name))

    assert context_failure.error_code == "CONTEXT_UNAVAILABLE"
    assert execution_failure.error_code == "EXECUTION_FAILED"
    for output in (context_failure, execution_failure):
        _assert_catalogued(output)
        assert EMAIL not in repr(output)


@pytest.mark.parametrize("name", SPECIALISTS)
def test_personal_data_never_reaches_the_model_or_the_output(name) -> None:
    generator = Generator(_valid(name).replace("porque sí", f"escribir a {EMAIL}"))
    output = _specialist(name, generator=generator, executor=Executor()).execute(
        _request(name)
    )

    sent = generator.seen[0]
    assert EMAIL not in sent.masked_user_message
    assert EMAIL not in sent.persisted_context
    assert EMAIL not in repr(output)
    assert output.verification_status == "PASSED"
    assert output.safe_metrics == {"precision": 0.9, "recall": 0.6}


def test_every_safe_code_the_orchestrator_can_surface_is_explained() -> None:
    informational = {"LEASE_ACQUIRED", "LEASE_RELEASED"}  # audit notes, not failures
    missing = sorted(
        code for code in _SAFE_AUDIT_REASONS - informational if code not in CATALOG
    )

    assert missing == []
