from __future__ import annotations

import dataclasses
import json
from typing import Any, Callable
from uuid import UUID

from src.application.dtos.adversarial_review_alert_dtos import (
    AdversarialReviewAlertInput,
    AdversarialReviewAlertOutput,
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
from src.application.ports.workflow_port import WorkflowStepStatus
from src.application.ports.workflow_status_port import (
    WorkflowStatusReporter,
    WorkflowStatusUpdate,
)

# Same bound as classification's ReAct loop, same reason: a model that never
# converges can't loop forever.
MAX_REACT_ITERATIONS = 6

_SYSTEM_PROMPT = (
    "You are a fraud classification auditor performing adversarial review. "
    "You are given an alert, its profiling data, and a fraud analyst's "
    "classification decision together with the analyst's full reasoning "
    "trace. Your job is to find errors in that decision: unsupported "
    "conclusions, misapplied taxonomy, ignored evidence, or logical gaps. "
    "You have access to the same investigation tools the analyst used, in "
    "any order, as many or as few times as you need, to independently "
    "verify their claims.\n\n"
    "Tools:\n"
    "- get_similar_frauds: given a short text query, returns similar past "
    "fraud cases (case_id, summary, outcome, similarity_score).\n"
    "- get_similar_taxonomy: given a short text query, returns similar "
    "fraud taxonomy entries (code, name, description, similarity_score).\n"
    "- get_similar_modus_operandi: given a short text query, returns "
    "similar modus operandi patterns (pattern_id, description, "
    "similarity_score).\n\n"
    "Respond using ONLY one of these two formats, nothing else:\n\n"
    "Thought: <your reasoning>\n"
    "Action: <one of get_similar_frauds, get_similar_taxonomy, "
    "get_similar_modus_operandi>\n"
    "Action Input: <a short text query for that tool>\n\n"
    "or, when you are ready to conclude:\n\n"
    "Thought: <your reasoning>\n"
    'Final Answer: {"has_issues": true|false, '
    '"feedback": "<specific correction for the analyst to act on, empty '
    'if no issues>", "weak_points": ["<short issue>", ...], '
    '"reasoning": "<brief justification>"}\n\n'
    "Only set has_issues to true when you find a concrete, actionable "
    "problem - do not flag the decision just because it is close to the "
    "line."
)

_INITIAL_PROMPT = (
    "Alert data, profiling results, and the classification under "
    "review:\n{data}"
)


def _serializable(value: Any) -> Any:
    return dataclasses.asdict(value) if dataclasses.is_dataclass(value) else value


def _review_context(input: AdversarialReviewAlertInput) -> dict[str, Any]:
    pre_process = input.pre_process
    return {
        "mandatory_fields": pre_process.mandatory_fields,
        "optional_fields": pre_process.optional_fields,
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
        status_reporter: WorkflowStatusReporter | None = None,
        workflow_execution_id: UUID | None = None,
        step_id: UUID | None = None,
    ) -> None:
        self._llm_factory = llm_unit_of_work_factory
        self._monitoring = monitoring
        self._model = model
        self._status_reporter = status_reporter
        self._workflow_execution_id = workflow_execution_id
        self._step_id = step_id
        self._tools: dict[str, Callable[[str], list[Any]]] = {
            "get_similar_frauds": similar_fraud_case_port.find_similar,
            "get_similar_taxonomy": fraud_taxonomy_port.find_similar,
            "get_similar_modus_operandi": modus_operandi_port.find_similar,
        }

    def _report_progress(self, detail: str) -> None:
        if self._status_reporter is None or self._workflow_execution_id is None:
            return
        self._status_reporter.report(
            WorkflowStatusUpdate(
                workflow_execution_id=self._workflow_execution_id,
                step_name="adversarial",
                step_id=self._step_id,
                status=WorkflowStepStatus.RUNNING,
                detail={"output": {"progress": detail}},
            )
        )

    def _run_tool(self, name: str, query: str) -> str:
        tool = self._tools.get(name)
        if tool is None:
            return f"Unknown tool '{name}'. Available tools: {', '.join(self._tools)}"
        results = tool(query)
        return json.dumps([_serializable(r) for r in results], default=str)

    def execute(
        self, input: AdversarialReviewAlertInput
    ) -> AdversarialReviewAlertOutput:
        self._report_progress("react_reasoning_start")
        messages = [
            LLMMessage(role=LLMMessageRole.SYSTEM, content=_SYSTEM_PROMPT),
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
            operation_name="adversarial",
        )

        for _ in range(MAX_REACT_ITERATIONS):
            result = uow.invoke(messages)
            messages.append(
                LLMMessage(role=LLMMessageRole.ASSISTANT, content=result.content)
            )
            action, action_input, final_answer = _parse_react_step(result.content)
            if final_answer is not None:
                output = _parse_final_answer(final_answer)
                output.cot = _transcript(messages)
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
        )
