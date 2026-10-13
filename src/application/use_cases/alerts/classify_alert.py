from __future__ import annotations

import dataclasses
import json
from typing import Any, Callable
from uuid import UUID

from src.application.dtos.classify_alert_dtos import (
    UNKNOWN,
    ClassifyAlertInput,
    ClassifyAlertOutput,
)
from src.application.ports.fraud_similarity_port import SimilarFraudCasePort
from src.application.ports.fraud_taxonomy_port import FraudTaxonomyPort
from src.application.ports.llm_unit_of_work_port import (
    LLMMessage,
    LLMMessageRole,
    LLMUnitOfWorkFactory,
)
from src.application.ports.modus_operandi_port import ModusOperandiPort
from src.application.ports.monitoring_port import MonitoringPort
from src.application.ports.watchlist_port import WatchlistRepository
from src.application.ports.workflow_port import WorkflowStepStatus
from src.application.ports.workflow_status_port import (
    WorkflowStatusReporter,
    WorkflowStatusUpdate,
)
from src.application.use_cases.watchlists.check_watchlist_membership import (
    WatchlistMatch,
)
from src.application.use_cases.research.research_tool import BoundedResearchTool
from src.domain.alerts.calculator import CalculatorError, safe_calculate

# ReAct loop: model alternates Thought/Action/Action Input turns (each
# fulfilled by us calling one of the three tools and appending an
# Observation) until it emits a Final Answer. Bounded (by
# ClassificationConfig.max_thought_iterations, defaulting to this constant)
# so a model that never converges can't loop forever.
MAX_REACT_ITERATIONS = 6

_VALID_DETERMINATIONS = {"fraud", "not_fraud", UNKNOWN}

_INTRO = (
    "Eres un analista de clasificación de fraude. Decide (1) si la alerta "
    "es fraude, y (2) su clasificación de fraude (etiqueta de "
    "tipología/taxonomía). Puedes investigar usando las siguientes "
    "herramientas, en cualquier orden, tantas o tan pocas veces como "
    "necesites - tú decides.\n\n"
)

# One description per tool this use case can offer, keyed the same as
# ClassifyAlertUseCase._tools - the system prompt only lists (and only
# allows as an Action) whichever subset ends up enabled, so a disabled
# tool's description never leaks into a prompt where calling it would fail.
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
        "check_watchlist: no necesita Action Input (deja un guion \"-\") - "
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
    'Final Answer: {{"is_fraud": "fraud|not_fraud|unknown", '
    '"fraud_classification": "<etiqueta de taxonomía o unknown>", '
    '"reasoning": "<justificación breve>"}}\n\n'
    "Si la evidencia es insuficiente o no concluyente, define tanto "
    'is_fraud como fraud_classification como "unknown" en lugar de '
    "adivinar."
)


def _build_system_prompt(tool_names: list[str], output_labels: list[str] | None) -> str:
    tools_block = "Herramientas:\n" + "\n".join(
        f"- {_TOOL_DESCRIPTIONS[name]}" for name in tool_names if name in _TOOL_DESCRIPTIONS
    )
    prompt = _INTRO + tools_block + "\n\n" + _RESPONSE_FORMAT.format(
        tool_names=", ".join(tool_names) or "ninguna - concluye directamente"
    )
    if output_labels:
        prompt += (
            "\n\nfraud_classification debe ser exactamente una de estas "
            f"etiquetas, o \"unknown\": {', '.join(output_labels)}."
        )
    return prompt


_INITIAL_PROMPT = "Datos de la alerta y resultados del perfilamiento:\n{data}"


def _serializable(value: Any) -> Any:
    return dataclasses.asdict(value) if dataclasses.is_dataclass(value) else value


def _alert_context(input: ClassifyAlertInput) -> dict[str, Any]:
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


def _parse_final_answer(raw: str) -> ClassifyAlertOutput:
    try:
        data = json.loads(raw)
        is_fraud = str(data.get("is_fraud", UNKNOWN))
        if is_fraud not in _VALID_DETERMINATIONS:
            is_fraud = UNKNOWN
        return ClassifyAlertOutput(
            is_fraud=is_fraud,
            fraud_classification=str(data.get("fraud_classification") or UNKNOWN),
            reasoning=str(data.get("reasoning", "")),
        )
    except (json.JSONDecodeError, AttributeError):
        return ClassifyAlertOutput(
            is_fraud=UNKNOWN,
            fraud_classification=UNKNOWN,
            reasoning=raw,
        )


class ClassifyAlertUseCase:
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
        output_labels: list[str] | None = None,
        max_iterations: int | None = None,
        # "classification" for the Clasificación step (the default, and
        # the only caller until Detector started reusing this same class -
        # same ReAct/is_fraud/fraud_classification shape, different
        # prompt/tools/config). Drives both the WorkflowStatusUpdate
        # step_name below and the LLM call's operation_name, so progress
        # reporting/OTLP spans land under the right step either way.
        step_name: str = "classification",
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
        self._output_labels = list(output_labels) if output_labels else None
        self._max_iterations = max_iterations or MAX_REACT_ITERATIONS
        self._watchlist_repository = watchlist_repository
        self._watchlist_ids = watchlist_ids
        self._watchlist_compare_field = watchlist_compare_field
        # Set fresh per execute() call - the value being checked depends on
        # the alert being reviewed, not on how this use case was built.
        self._watchlist_value: str | None = None

        self._tools: dict[str, Callable[[str], list[Any] | str]] = {
            "get_similar_frauds": similar_fraud_case_port.find_similar,
            "get_similar_taxonomy": fraud_taxonomy_port.find_similar,
            "get_similar_modus_operandi": modus_operandi_port.find_similar,
            "calculator": self._calculator_tool,
        }
        if watchlist_repository is not None and watchlist_ids and watchlist_compare_field:
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

        base_prompt = _build_system_prompt(list(self._tools), self._output_labels)
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

    def _invalid_label_observation(self, label: str) -> str:
        return (
            f'Observation: "{label}" no es una etiqueta de '
            "fraud_classification válida. Etiquetas válidas: "
            f"{', '.join(self._output_labels or [])} (o \"{UNKNOWN}\" si no "
            "estás seguro). Responde de nuevo con un Final Answer usando "
            "una etiqueta válida."
        )

    def execute(self, input: ClassifyAlertInput) -> ClassifyAlertOutput:
        output = self._execute(input)
        if self._vector_store_research is not None:
            output.vector_store_interactions = list(
                self._vector_store_research.interactions
            )
        return output

    def _execute(self, input: ClassifyAlertInput) -> ClassifyAlertOutput:
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
                    data=json.dumps(_alert_context(input), default=str)
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
                if (
                    self._output_labels
                    and output.fraud_classification not in self._output_labels
                    and output.fraud_classification != UNKNOWN
                ):
                    # Invalid label and reasoning budget still open: feed
                    # back a correction and let the model retry instead of
                    # silently accepting or hard-failing on an out-of-
                    # catalog classification.
                    messages.append(
                        LLMMessage(
                            role=LLMMessageRole.USER,
                            content=self._invalid_label_observation(
                                output.fraud_classification
                            ),
                        )
                    )
                    continue
                output.cot = _transcript(messages)
                output.input_tokens = input_tokens
                output.output_tokens = output_tokens
                output.expected_classification = input.expected_classification
                output.ground_truth_tipo = input.ground_truth_tipo
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

        return ClassifyAlertOutput(
            is_fraud=UNKNOWN,
            fraud_classification=UNKNOWN,
            reasoning=(
                "Could not reach a conclusion within the allotted "
                "reasoning steps."
            ),
            cot=_transcript(messages),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            expected_classification=input.expected_classification,
            ground_truth_tipo=input.ground_truth_tipo,
        )
