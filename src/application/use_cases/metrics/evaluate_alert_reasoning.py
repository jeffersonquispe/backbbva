"""EvaluateAlertReasoning (D6): sampled LLM-judge for the /monitor KPIs
"Alucinaciones" and "Uso correcto de datos".

Judges a finished alert's reasoning steps (detector, classification,
adversarial reviews, analyst) against the evidence those steps actually
had: the alert payload, pre-processing / profiling outputs, and each
step's own tool observations (its ReAct trace), delegated research and
vector-store findings, and XGBoost output. Verdict: hallucination (a claim
not supported by that evidence), data_use_correct (the evidence was read
and weighed correctly), and a short rationale.

Exactly-once, in this order, so any retry converges:
1. A verdict already stored for the alert is reused (never re-judged).
2. Otherwise judge, and store it - first writer wins
   (AlertReasoningEvaluationRepository.create), so two concurrent runs end
   up counting the same verdict.
3. Count the STORED verdict with MetricsRollupRepository.apply_once under
   the marker ("evaluation", <alert id>). A crash between 2 and 3 is healed
   by the retry going through 1 -> 3; a redelivery after 3 finds the marker.

Raw prompt/completion content never goes into this use case's span (only
verdict flags and sizes); the LLM unit of work records content only when
OTEL_CAPTURE_LLM_CONTENT is on."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any
from uuid import UUID

from src.application.dtos.reasoning_evaluation_dtos import (
    EvaluateAlertReasoningInput,
    EvaluateAlertReasoningOutput,
)
from src.application.ports.alert_port import (
    AlertRepository,
)
from src.application.ports.alert_reasoning_evaluation_port import (
    AlertReasoningEvaluationRecord,
    AlertReasoningEvaluationRepository,
    ReasoningEvaluationStatus,
)
from src.application.ports.clock_port import Clock
from src.application.ports.llm_unit_of_work_factory_port import LLMUnitOfWorkFactory
from src.application.ports.llm_unit_of_work_port import LLMMessage, LLMMessageRole
from src.application.ports.metrics_rollup_port import (
    MetricsRollupRepository,
    RollupApplyMarker,
)
from src.application.ports.monitoring_port import MonitoringPort
from src.application.ports.workflow_port import WorkflowExecutionRepository
from src.application.ports.workflow_step_execution_port import (
    WorkflowStepExecutionRepository,
)
from src.application.runtime_defaults import resolve_clock
from src.application.use_cases.metrics.technical_rollup_contribution import (
    evaluation_contribution,
    technical_alert_dimensions,
    technical_deltas,
)
from src.domain.alerts.entities import (
    AlertRecord,
)
from src.domain.workflows.entities import (
    WorkflowStepExecutionRecord,
    WorkflowStepStatus,
)

MARKER_SCOPE = "evaluation"

# Steps whose conclusions are judged, in pipeline order.
REASONING_STEPS: tuple[str, ...] = (
    "detector",
    "detector_adversarial",
    "classification",
    "adversarial",
    "analyst",
)
# Steps whose output is input evidence for the reasoning steps.
EVIDENCE_STEPS: tuple[str, ...] = ("pre_process", "profiling")

# Character budgets so one alert's judge prompt stays bounded.
MAX_EVIDENCE_CHARS = 40_000
MAX_STEP_CHARS = 12_000
MAX_RATIONALE_CHARS = 600
MAX_STEP_NOTE_CHARS = 300
# One extra judge call when the first answer cannot be parsed; more would spend
# tokens on a prompt/model that is not following the format.
MAX_JUDGE_ATTEMPTS = 2

# Bump on any change to the judge prompt or criteria: it is stored on every
# verdict so rates from different versions are never mixed up unnoticed.
# v1: one verdict per alert. v2: one per reasoning step, alert verdict derived.
PROMPT_VERSION = "v2"

_SYSTEM_PROMPT = (
    "Eres un auditor de calidad de un agente de revisión de alertas de "
    "fraude bancario. Recibes (1) la EVIDENCIA que el agente tenía: el "
    "payload de la alerta, el pre-procesamiento y el perfilamiento; y (2) "
    "los PASOS de razonamiento del agente, cada uno con su conclusión, su "
    "razonamiento y la evidencia propia que obtuvo con herramientas "
    "(trazas de observaciones, investigación delegada, Vector Store, "
    "salida del modelo XGBoost).\n"
    "Evalúa sólo contra esa evidencia, nunca contra conocimiento externo:\n"
    "- hallucination = true si algún paso afirma un hecho, cifra o "
    "resultado que no está en la evidencia disponible para ese paso.\n"
    "- data_use_correct = true si los pasos leyeron e interpretaron "
    "correctamente los datos que citan y no ignoraron evidencia decisiva "
    "en contra de su conclusión.\n"
    "Emite un veredicto por cada paso listado en PASOS, usando exactamente "
    "su nombre entre corchetes. Responde SOLO con un objeto JSON, sin texto "
    "adicional: "
    '{"steps": {"<nombre del paso>": {"hallucination": true|false, '
    '"data_use_correct": true|false, "note": "<una frase en español>"}}, '
    '"rationale": "<máximo 2 frases en español sobre el conjunto>"}'
)

_USER_PROMPT = "EVIDENCIA:\n{evidence}\n\nPASOS DE RAZONAMIENTO:\n{steps}"


def judge_overlaps_reasoning(
    judge_model: str, reasoning_models: dict[str, str]
) -> tuple[str, ...]:
    """Steps whose model is the judge's own. A judge that grades its own model's
    output is lenient with it, so the rates are only trustworthy when the judge
    is a different model from the one that reasoned (PENDIENTES evaluator 5.1)."""
    if not judge_model:
        return ()
    return tuple(
        sorted(step for step, model in reasoning_models.items() if model == judge_model)
    )


def is_sampled_for_evaluation(alert_id: UUID, sample_rate: float) -> bool:
    """Deterministic per alert: the same alert always gets the same answer
    (a Celery retry of the review never flips it). rate <= 0 disables."""
    if sample_rate <= 0:
        return False
    if sample_rate >= 1:
        return True
    digest = hashlib.sha256(str(alert_id).encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64 < sample_rate


class EvaluateAlertReasoning:
    def __init__(
        self,
        llm_unit_of_work_factory: LLMUnitOfWorkFactory,
        monitoring: MonitoringPort,
        model: str,
        alert_repository: AlertRepository,
        workflow_repository: WorkflowExecutionRepository,
        step_repository: WorkflowStepExecutionRepository,
        evaluation_repository: AlertReasoningEvaluationRepository,
        rollup_repository: MetricsRollupRepository,
        timezone_name: str,
        clock: Clock | None = None,
    ) -> None:
        self._llm_factory = llm_unit_of_work_factory
        self._monitoring = monitoring
        self._model = model
        self._alerts = alert_repository
        self._workflows = workflow_repository
        self._steps = step_repository
        self._evaluations = evaluation_repository
        self._rollups = rollup_repository
        self._timezone_name = timezone_name
        self._clock = resolve_clock(clock)

    def execute(
        self, input: EvaluateAlertReasoningInput
    ) -> EvaluateAlertReasoningOutput:
        alert = self._alerts.get(input.alert_id)
        if alert is None:
            return EvaluateAlertReasoningOutput(evaluation=None)
        stored = self._evaluations.get(input.alert_id)
        if stored is None:
            judged = self._judge(alert, input.workflow_execution_id)
            if judged is None:
                return EvaluateAlertReasoningOutput(evaluation=None)
            stored = self._evaluations.create(judged)
        return EvaluateAlertReasoningOutput(
            evaluation=stored, counted=self._count(alert, stored)
        )

    def _count(
        self, alert: AlertRecord, record: AlertReasoningEvaluationRecord
    ) -> bool:
        part = evaluation_contribution(
            technical_alert_dimensions(alert.metrics, alert.status),
            hallucination=record.hallucination,
            data_use_correct=record.data_use_correct,
        )
        deltas = technical_deltas(
            [part], alert.created_at, self._clock.now(), self._timezone_name
        )
        return self._rollups.apply_once(
            deltas, RollupApplyMarker(scope=MARKER_SCOPE, key=str(record.alert_id))
        )

    def _judge(
        self, alert: AlertRecord, workflow_execution_id: UUID
    ) -> AlertReasoningEvaluationRecord | None:
        workflow = self._workflows.get(workflow_execution_id)
        if workflow is None:
            return None
        latest = _latest_succeeded(self._steps.list_by_workflow(workflow_execution_id))
        steps = {
            name: _reasoning_view(latest[name].output or {})
            for name in REASONING_STEPS
            if name in latest
        }
        if not steps:
            return None
        evidence = {
            "alert_input": alert.input,
            **{name: latest[name].output for name in EVIDENCE_STEPS if name in latest},
        }
        evidence_text = _bounded(evidence, MAX_EVIDENCE_CHARS)
        steps_text = "\n".join(
            f"[{name}] {_bounded(view, MAX_STEP_CHARS)}" for name, view in steps.items()
        )

        with self._monitoring.start(
            "evaluate_alert_reasoning",
            "evaluation",
            metadata={"alert_id": str(alert.id), "judge_model": self._model},
        ) as span:
            # Sizes and step names only - never the prompt itself.
            span.write_input(
                {
                    "steps": list(steps),
                    "evidence_chars": len(evidence_text),
                    "steps_chars": len(steps_text),
                }
            )
            uow = self._llm_factory.create(
                model=self._model,
                monitoring=self._monitoring,
                operation_name="evaluate_alert_reasoning",
            )
            messages = [
                LLMMessage(role=LLMMessageRole.SYSTEM, content=_SYSTEM_PROMPT),
                LLMMessage(
                    role=LLMMessageRole.USER,
                    content=_USER_PROMPT.format(
                        evidence=evidence_text, steps=steps_text
                    ),
                ),
            ]
            result = uow.invoke(messages)
            attempts = 1
            hallucination, data_use_correct, rationale, step_verdicts = _parse_verdict(
                result.content, expected_steps=tuple(steps)
            )
            input_tokens = result.input_tokens or 0
            output_tokens = result.output_tokens or 0
            while (
                hallucination is None or data_use_correct is None
            ) and attempts < MAX_JUDGE_ATTEMPTS:
                attempts += 1
                result = uow.invoke(messages)
                input_tokens += result.input_tokens or 0
                output_tokens += result.output_tokens or 0
                hallucination, data_use_correct, rationale, step_verdicts = (
                    _parse_verdict(result.content, expected_steps=tuple(steps))
                )
            status = (
                ReasoningEvaluationStatus.EVALUATED
                if hallucination is not None and data_use_correct is not None
                else ReasoningEvaluationStatus.INVALID
            )
            span.write_result(
                {
                    "status": status.value,
                    "hallucination": hallucination,
                    "data_use_correct": data_use_correct,
                    "prompt_version": PROMPT_VERSION,
                    "attempts": attempts,
                }
            )
        return AlertReasoningEvaluationRecord(
            alert_id=alert.id,
            workflow_execution_id=workflow_execution_id,
            status=status,
            hallucination=hallucination,
            data_use_correct=data_use_correct,
            rationale=rationale,
            judge_model=result.model or self._model,
            evaluated_at=self._clock.now(),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            prompt_version=PROMPT_VERSION,
            step_verdicts=step_verdicts,
            attempts=attempts,
        )


def _latest_succeeded(
    steps: list[WorkflowStepExecutionRecord],
) -> dict[str, WorkflowStepExecutionRecord]:
    """Per step name, its last successful execution (the one the pipeline
    went on with after feedback loops / retries)."""
    latest: dict[str, WorkflowStepExecutionRecord] = {}
    for step in sorted(steps, key=lambda s: (s.created_at, str(s.id))):
        if step.status == WorkflowStepStatus.SUCCEEDED and step.output is not None:
            latest[step.step_name] = step
    return latest


_CONCLUSION_FIELDS = (
    "is_fraud",
    "fraud_classification",
    "decision",
    "requires_classification_feedback",
    "feedback",
    "weak_points",
)
_OWN_EVIDENCE_FIELDS = (
    "cot",
    "research_delegations",
    "vector_store_interactions",
    "model_output",
)


def _reasoning_view(output: dict[str, Any]) -> dict[str, Any]:
    """What the judge needs from one reasoning step: its conclusion and
    reasoning (the claims) plus the evidence it gathered itself."""
    return {
        "conclusion": {
            k: output[k] for k in _CONCLUSION_FIELDS if output.get(k) is not None
        },
        "reasoning": output.get("reasoning"),
        "own_evidence": {
            k: output[k]
            for k in _OWN_EVIDENCE_FIELDS
            if output.get(k) not in (None, "", [])
        },
    }


def _bounded(value: Any, limit: int) -> str:
    text = json.dumps(value, default=str, ensure_ascii=False)
    if len(text) <= limit:
        return text
    return text[:limit] + " ...[truncado]"


_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


def _parse_verdict(
    raw: str, expected_steps: tuple[str, ...] = ()
) -> tuple[bool | None, bool | None, str, dict[str, dict[str, object]]]:
    """(hallucination, data_use_correct, rationale, per-step verdicts).

    v2 answers carry a verdict per step and the alert-level flags are derived:
    hallucination if ANY step hallucinated, data_use_correct only if ALL steps
    used the data correctly. Answers in the v1 shape (flags at the top level,
    no steps) are still accepted, with no per-step detail."""
    unreadable: tuple[bool | None, bool | None, str, dict[str, dict[str, object]]] = (
        None,
        None,
        "Respuesta del evaluador no interpretable.",
        {},
    )
    match = _JSON_OBJECT.search(raw or "")
    try:
        data = json.loads(match.group(0) if match else raw)
    except (json.JSONDecodeError, TypeError):
        return unreadable
    if not isinstance(data, dict):
        return unreadable
    rationale = str(data.get("rationale") or "")[:MAX_RATIONALE_CHARS]
    step_verdicts = _step_verdicts(data.get("steps"), expected_steps)
    if step_verdicts:
        return (
            any(v["hallucination"] for v in step_verdicts.values()),
            all(v["data_use_correct"] for v in step_verdicts.values()),
            rationale,
            step_verdicts,
        )
    hallucination = data.get("hallucination")
    data_use_correct = data.get("data_use_correct")
    return (
        hallucination if isinstance(hallucination, bool) else None,
        data_use_correct if isinstance(data_use_correct, bool) else None,
        rationale,
        {},
    )


def _step_verdicts(
    raw: Any, expected_steps: tuple[str, ...]
) -> dict[str, dict[str, object]]:
    """Only the steps that were actually judged and have both flags as booleans;
    an answer that skips a step is not trusted as a per-step verdict."""
    if not isinstance(raw, dict):
        return {}
    verdicts: dict[str, dict[str, object]] = {}
    for name, value in raw.items():
        if expected_steps and name not in expected_steps:
            continue
        if not isinstance(value, dict):
            continue
        hallucination = value.get("hallucination")
        data_use_correct = value.get("data_use_correct")
        if not isinstance(hallucination, bool) or not isinstance(
            data_use_correct, bool
        ):
            continue
        verdicts[name] = {
            "hallucination": hallucination,
            "data_use_correct": data_use_correct,
            "note": str(value.get("note") or "")[:MAX_STEP_NOTE_CHARS],
        }
    if expected_steps and set(verdicts) != set(expected_steps):
        return {}
    return verdicts
