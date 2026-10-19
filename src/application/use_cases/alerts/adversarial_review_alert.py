from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable
from typing import Any
from uuid import UUID

from src.application.dtos.adversarial_review_alert_dtos import (
    AdversarialReviewAlertInput,
    AdversarialReviewAlertOutput,
)
from src.application.ports.fraud_similarity_port import SimilarFraudCasePort
from src.application.ports.fraud_taxonomy_port import FraudTaxonomyPort
from src.application.ports.llm_unit_of_work_factory_port import LLMUnitOfWorkFactory
from src.application.ports.llm_unit_of_work_port import LLMMessage, LLMMessageRole
from src.application.ports.modus_operandi_port import ModusOperandiPort
from src.application.ports.monitoring_port import MonitoringPort
from src.application.ports.watchlist_port import WatchlistRepository
from src.application.ports.workflow_status_port import (
    WorkflowStatusReporter,
    WorkflowStatusUpdate,
)
from src.application.use_cases.research.research_tool import BoundedResearchTool
from src.application.use_cases.watchlists.check_watchlist_membership import (
    WatchlistMatch,
)
from src.domain.alerts.calculator import CalculatorError, safe_calculate
from src.domain.workflows.entities import (
    WorkflowStepStatus,
)

# Same bound as classification's ReAct loop, same reason: a model that never
# converges can't loop forever. Overridable per call (max_iterations) -
# AdversarialConfig itself has no such field today, only
# DetectorAdversarialConfig does, but the param is here so both configs can
# drive the same use case once Detector's own pipeline step exists.
MAX_REACT_ITERATIONS = 6

_INTRO = (
    "Eres un auditor de clasificación de fraude que realiza una revisión "
    "adversarial. Se te entrega una alerta, sus datos de perfilamiento y "
    "la decisión de clasificación de un analista de fraude junto con su "
    "razonamiento completo. Tu trabajo es encontrar errores en esa "
    "decisión: conclusiones sin sustento, taxonomía mal aplicada, "
    "evidencia ignorada o vacíos lógicos. Tienes acceso a las mismas "
    "herramientas de investigación que usó el analista, en cualquier "
    "orden, tantas o tan pocas veces como necesites, para verificar sus "
    "afirmaciones de forma independiente.\n\n"
)

# Same tool catalog as classify_alert.py's _TOOL_DESCRIPTIONS - only the
# subset actually enabled for this review ends up in the prompt.
_TOOL_DESCRIPTIONS = {
    "get_similar_frauds": (
        "get_similar_frauds: dada una consulta corta de texto, devuelve "
        "casos de fraude pasados similares (case_id, summary, outcome, "
        "similarity_score)."
    ),
    "get_similar_taxonomy": (
        "get_similar_taxonomy: dada una consulta corta de texto, devuelve "
        "entradas de taxonomía de fraude similares (code, name, "
        "description, similarity_score)."
    ),
    "get_similar_modus_operandi": (
        "get_similar_modus_operandi: dada una consulta corta de texto, "
        "devuelve patrones de modus operandi similares (pattern_id, "
        "description, similarity_score)."
    ),
    "calculator": (
        "calculator: dada una expresión aritmética (ej. '1500000 / 3'), "
        "devuelve su resultado numérico exacto."
    ),
    "search_vector_store": (
        "search_vector_store: busca en la base de conocimiento (vector "
        "store) los insights o la pregunta concreta que "
        "quieres investigar; devuelve hallazgos (taxonomías, modus operandi, "
        "casos similares, banderas) con su similitud. Puedes llamarlo varias "
        "veces con preguntas distintas, hasta agotar su límite de "
        "interacciones."
    ),
    "check_watchlist": (
        'check_watchlist: no necesita Action Input (deja un guion "-") - '
        "revisa si el valor relevante de esta alerta pertenece a alguna de "
        "las listas configuradas y devuelve las coincidencias."
    ),
}

_RESPONSE_FORMAT = (
    "Responde usando SOLO uno de estos dos formatos, nada más:\n\n"
    "Thought: <tu razonamiento>\n"
    "Action: <una de {tool_names}>\n"
    "Action Input: <una consulta corta de texto para esa herramienta>\n\n"
    "o, cuando estés listo para concluir:\n\n"
    "Thought: <tu razonamiento>\n"
    'Final Answer: {{"has_issues": true|false, '
    '"feedback": "<corrección específica para que el analista actúe, '
    'vacío si no hay problemas>", "weak_points": ["<problema breve>", '
    '...], "reasoning": "<justificación breve>"}}\n\n'
    "Solo define has_issues como true cuando encuentres un problema "
    "concreto y accionable - no señales la decisión solo porque esté "
    "cerca del límite."
)


def _build_system_prompt(tool_names: list[str]) -> str:
    tools_block = "Herramientas:\n" + "\n".join(
        f"- {_TOOL_DESCRIPTIONS[name]}"
        for name in tool_names
        if name in _TOOL_DESCRIPTIONS
    )
    return (
        _INTRO
        + tools_block
        + "\n\n"
        + _RESPONSE_FORMAT.format(
            tool_names=", ".join(tool_names) or "ninguna - concluye directamente"
        )
    )


_INITIAL_PROMPT = (
    "Datos de la alerta, resultados del perfilamiento y la clasificación "
    "en revisión:\n{data}"
)


def _serializable(value: Any) -> Any:
    return (
        dataclasses.asdict(value)
        if dataclasses.is_dataclass(value) and not isinstance(value, type)
        else value
    )


def _review_context(input: AdversarialReviewAlertInput) -> dict[str, Any]:
    pre_process = input.pre_process
    return {
        "input": pre_process.input,
        "history": pre_process.history,
        "roles": pre_process.roles,
        "enrichment": {
            key: _serializable(value) for key, value in pre_process.enrichment.items()
        },
        "user_profile": input.profile.user_profile,
        "transaction_profile": input.profile.transaction_profile,
        "transactional_profile": input.profile.transactional_profile,
        "classification": {
            "is_fraud": input.classification.is_fraud,
            "fraud_classification": input.classification.fraud_classification,
            "reasoning": input.classification.reasoning,
            "chain_of_thought": input.classification.cot,
        },
    }


def _extract_after(text: str, marker: str) -> str | None:
    idx = text.find(marker)
    if idx == -1:
        return None
    return text[idx + len(marker) :].strip()


def _parse_react_step(
    content: str,
) -> tuple[str | None, str | None, str | None]:
    """Returns (action, action_input, final_answer_json)."""
    final_answer = _extract_after(content, "Final Answer:")
    if final_answer is not None:
        return None, None, final_answer

    action = _extract_after(content, "Action:")
    action_input = _extract_after(content, "Action Input:")
    if action is not None:
        action = action.splitlines()[0].strip()
    if action_input is not None:
        action_input = action_input.splitlines()[0].strip()
    return action, action_input, None


def _transcript(messages: list[LLMMessage]) -> str:
    # Skip the system prompt and the initial data dump (index 0, 1) - only
    # the actual Thought/Action/Observation turns are the CoT.
    return "\n\n".join(m.content for m in messages[2:])


def _parse_final_answer(raw: str) -> AdversarialReviewAlertOutput:
    try:
        data = json.loads(raw)
        weak_points = data.get("weak_points") or []
        if not isinstance(weak_points, list):
            weak_points = [str(weak_points)]
        return AdversarialReviewAlertOutput(
            requires_classification_feedback=bool(data.get("has_issues", False)),
            feedback=str(data.get("feedback") or ""),
            weak_points=[str(point) for point in weak_points],
            reasoning=str(data.get("reasoning", "")),
        )
    except (json.JSONDecodeError, AttributeError):
        # Malformed output can't be trusted to certify the classification -
        # treat it as an issue so it routes back for another attempt
        # instead of silently passing.
        return AdversarialReviewAlertOutput(
            requires_classification_feedback=True,
            feedback="Adversarial review returned a malformed final answer.",
            reasoning=raw,
        )


class AdversarialReviewAlertUseCase:
    def __init__(
        self,
        llm_unit_of_work_factory: LLMUnitOfWorkFactory,
        monitoring: MonitoringPort,
        model: str,
        similar_fraud_case_port: SimilarFraudCasePort,
        fraud_taxonomy_port: FraudTaxonomyPort,
        modus_operandi_port: ModusOperandiPort,
        system_prompt: str | None = None,
        extra_instructions: str | None = None,
        enabled_tools: set[str] | None = None,
        watchlist_repository: WatchlistRepository | None = None,
        watchlist_ids: list[str] | None = None,
        watchlist_compare_field: str | None = None,
        # Vector-store research tool, callable by the agent as a tool
        # (search_vector_store) up to its own interaction budget.
        vector_store_research: BoundedResearchTool | None = None,
        max_iterations: int | None = None,
        # "adversarial" for Adversarial (clasificador) (the default, and
        # the only caller until Adversarial (detector) started reusing
        # this same class). See ClassifyAlertUseCase's step_name for the
        # equivalent reasoning.
        step_name: str = "adversarial",
        status_reporter: WorkflowStatusReporter | None = None,
        workflow_execution_id: UUID | None = None,
        step_id: UUID | None = None,
    ) -> None:
        self._llm_factory = llm_unit_of_work_factory
        self._monitoring = monitoring
        self._model = model
        self._step_name = step_name
        self._status_reporter = status_reporter
        self._workflow_execution_id = workflow_execution_id
        self._step_id = step_id
        self._max_iterations = max_iterations or MAX_REACT_ITERATIONS
        self._watchlist_repository = watchlist_repository
        self._watchlist_ids = watchlist_ids
        self._watchlist_compare_field = watchlist_compare_field
        self._watchlist_value: str | None = None

        self._tools: dict[str, Callable[[str], list[Any] | str]] = {
            "get_similar_frauds": similar_fraud_case_port.find_similar,
            "get_similar_taxonomy": fraud_taxonomy_port.find_similar,
            "get_similar_modus_operandi": modus_operandi_port.find_similar,
            "calculator": self._calculator_tool,
        }
        if (
            watchlist_repository is not None
            and watchlist_ids
            and watchlist_compare_field
        ):
            self._tools["check_watchlist"] = self._check_watchlist_tool
        self._vector_store_research = vector_store_research
        if vector_store_research is not None:
            self._tools["search_vector_store"] = vector_store_research
        if enabled_tools is not None:
            self._tools = {
                name: tool
                for name, tool in self._tools.items()
                if name in enabled_tools or name == "search_vector_store"
            }

        base_prompt = _build_system_prompt(list(self._tools))
        if system_prompt is not None:
            # Full replace - test-run admin override, expected to already
            # include the ReAct protocol below. Wins outright over any
            # segment-level extra_instructions.
            self._system_prompt = system_prompt
        elif extra_instructions:
            self._system_prompt = (
                base_prompt
                + "\n\nInstrucciones adicionales para este segmento:\n"
                + extra_instructions
            )
        else:
            self._system_prompt = base_prompt

    def _calculator_tool(self, query: str) -> str:
        try:
            result = safe_calculate(query)
        except CalculatorError as exc:
            return f"Error: {exc}"
        return json.dumps({"expression": query, "result": result})

    def _check_watchlist_tool(self, _query: str) -> list[WatchlistMatch]:
        if (
            not self._watchlist_value
            or not self._watchlist_ids
            or self._watchlist_repository is None
        ):
            return []
        matched_ids = self._watchlist_repository.elements_containing(
            self._watchlist_ids, self._watchlist_value
        )
        if not matched_ids:
            return []
        return [
            WatchlistMatch(watchlist_id=watchlist.id, watchlist_name=watchlist.name)
            for watchlist_id in matched_ids
            if (watchlist := self._watchlist_repository.get(watchlist_id)) is not None
        ]

    def _report_progress(self, detail: str) -> None:
        if self._status_reporter is None or self._workflow_execution_id is None:
            return
        self._status_reporter.report(
            WorkflowStatusUpdate(
                workflow_execution_id=self._workflow_execution_id,
                step_name=self._step_name,
                step_id=self._step_id,
                status=WorkflowStepStatus.RUNNING,
                detail={"output": {"progress": detail}},
            )
        )

    def _run_tool(self, name: str, query: str) -> str:
        tool = self._tools.get(name)
        if tool is None:
            return f"Unknown tool '{name}'. Available tools: {', '.join(self._tools)}"
        result = tool(query)
        if isinstance(result, str):
            return result
        return json.dumps([_serializable(r) for r in result], default=str)

    def execute(
        self, input: AdversarialReviewAlertInput
    ) -> AdversarialReviewAlertOutput:
        output = self._execute(input)
        if self._vector_store_research is not None:
            output.vector_store_interactions = list(
                self._vector_store_research.interactions
            )
        return output

    def _execute(
        self, input: AdversarialReviewAlertInput
    ) -> AdversarialReviewAlertOutput:
        if self._watchlist_compare_field:
            fields = {
                **input.pre_process.input,
                **input.pre_process.mandatory_fields,
                **input.pre_process.optional_fields,
            }
            value = fields.get(self._watchlist_compare_field)
            self._watchlist_value = str(value) if value is not None else None

        self._report_progress("react_reasoning_start")
        messages = [
            LLMMessage(role=LLMMessageRole.SYSTEM, content=self._system_prompt),
            LLMMessage(
                role=LLMMessageRole.USER,
                content=_INITIAL_PROMPT.format(
                    data=json.dumps(_review_context(input), default=str)
                ),
            ),
        ]
        uow = self._llm_factory.create(
            model=self._model,
            monitoring=self._monitoring,
            operation_name=self._step_name,
        )

        input_tokens = 0
        output_tokens = 0
        for _ in range(self._max_iterations):
            result = uow.invoke(messages)
            input_tokens += result.input_tokens or 0
            output_tokens += result.output_tokens or 0
            messages.append(
                LLMMessage(role=LLMMessageRole.ASSISTANT, content=result.content)
            )
            action, action_input, final_answer = _parse_react_step(result.content)
            if final_answer is not None:
                output = _parse_final_answer(final_answer)
                output.cot = _transcript(messages)
                output.input_tokens = input_tokens
                output.output_tokens = output_tokens
                return output
            if action is None or action_input is None:
                break
            self._report_progress(f"tool_call:{action}")
            observation = self._run_tool(action, action_input)
            messages.append(
                LLMMessage(
                    role=LLMMessageRole.USER,
                    content=f"Observation: {observation}",
                )
            )

        # Same failure mode as a malformed final answer: an inconclusive
        # review can't certify the classification, so route it back.
        return AdversarialReviewAlertOutput(
            requires_classification_feedback=True,
            feedback=(
                "Adversarial review could not reach a conclusion within the "
                "allotted reasoning steps."
            ),
            reasoning="Could not reach a conclusion within the allotted reasoning steps.",
            cot=_transcript(messages),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
