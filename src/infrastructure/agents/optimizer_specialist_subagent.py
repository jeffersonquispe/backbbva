from __future__ import annotations

import json
import logging
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from src.application.ports.agent_experiment_component_port import (
    AgentExperimentComponentResolver,
)
from src.application.ports.agent_prompt_port import AgentPromptRepository
from src.application.ports.agent_specialist_executor_port import (
    AgentSpecialistExecutor,
)
from src.application.ports.agent_structured_generator_port import (
    AgentStructuredGenerationInput,
    AgentStructuredGenerator,
)
from src.application.ports.agent_subagent_port import (
    AgentSubagentInput,
    AgentSubagentOutput,
)
from src.application.ports.personal_data_masker_port import PersonalDataMasker
from src.domain.agents.experiment import ComponentVersionReference
from src.infrastructure.embedding.usage_meter import measure_embedding_usage

logger = logging.getLogger(__name__)


class OptimizerSpecialistSubagent:
    """Generates a typed experiment proposal using the session-pinned prompt."""

    def __init__(
        self,
        *,
        name: str,
        prompt_name: str,
        prompts: AgentPromptRepository,
        generator: AgentStructuredGenerator,
        masker: PersonalDataMasker,
        executor: AgentSpecialistExecutor | None = None,
        component_resolver: AgentExperimentComponentResolver | None = None,
    ) -> None:
        self._name = name
        self._prompt_name = prompt_name
        self._prompts = prompts
        self._generator = generator
        self._masker = masker
        self._executor = executor
        self._component_resolver = component_resolver

    @property
    def name(self) -> str:
        return self._name

    def execute(self, request: AgentSubagentInput) -> AgentSubagentOutput:
        reference = request.prompt_versions.get(self._prompt_name)
        if not reference:
            return AgentSubagentOutput(self.name, error_code="PROMPT_NOT_PINNED")
        try:
            prompt = self._prompts.get_version(
                self._prompt_name, int(reference["version"])
            )
        except (KeyError, TypeError, ValueError):
            return AgentSubagentOutput(self.name, error_code="PROMPT_UNAVAILABLE")
        if prompt is None or prompt.content_hash != reference.get("hash"):
            return AgentSubagentOutput(self.name, error_code="PROMPT_VERSION_MISMATCH")
        safe_scope = _mask_strings(request.scope, self._masker)
        safe_hypothesis = self._masker.mask(request.hypothesis).text
        context = {
            "scope": safe_scope,
            "budget": request.budget,
            "iteration": request.iteration_number,
            "objective_id": request.objective_id,
            "objective_version": request.objective_version,
            "objective": _objective_context(request),
            "project_map": request.project_map,
            "selected_project_lever": self.name,
        }
        safe_request = replace(
            request,
            scope=safe_scope,
            hypothesis=safe_hypothesis,
        )
        if self._executor is not None:
            try:
                context["domain_context"] = _mask_strings(
                    self._executor.context(safe_request), self._masker
                )
            except (RuntimeError, ValueError, TypeError):
                return AgentSubagentOutput(self.name, error_code="CONTEXT_UNAVAILABLE")
        persisted_context = json.dumps(
            context, ensure_ascii=False, default=_json_safe_default
        )
        payload: Any = None
        # One malformed or out-of-bounds proposal is a model slip, not a
        # failure worth stopping the session for: ask once more with the
        # contract restated before reporting GENERATION_INVALID.
        for attempt in range(_GENERATION_ATTEMPTS):
            message = (
                safe_hypothesis
                if attempt == 0
                else f"{safe_hypothesis}\n\n{_CONTRACT_REMINDER}"
            )
            try:
                raw = self._generator.generate(
                    AgentStructuredGenerationInput(
                        system_prompt=prompt.content,
                        persisted_context=persisted_context,
                        masked_user_message=message,
                    )
                )
            except (RuntimeError, ValueError, TypeError):
                return AgentSubagentOutput(self.name, error_code="GENERATION_FAILED")
            payload = _valid_proposal(self.name, raw)
            if payload is not None:
                break
            logger.warning(
                "Optimizer specialist %s proposal invalid (attempt %d)",
                self.name,
                attempt + 1,
            )
        if payload is None:
            return AgentSubagentOutput(self.name, error_code="GENERATION_INVALID")
        safe_payload = _mask_strings(payload, self._masker)
        if not isinstance(safe_payload, dict):
            return AgentSubagentOutput(self.name, error_code="GENERATION_INVALID")
        if self._executor is None:
            return AgentSubagentOutput(
                subagent=self.name,
                contribution=safe_payload,
                verification_status="PENDING_VERIFICATION",
                safe_metrics={"proposal_fields": len(payload["experiment"])},
            )
        # Embedding work is attributed to the session even when the
        # execution fails, so the ledger reflects what was really consumed.
        with measure_embedding_usage() as embedding_usage:
            try:
                execution = self._executor.execute(
                    safe_request, safe_payload["experiment"]
                )
            except (RuntimeError, ValueError, TypeError) as error:
                logger.warning(
                    "Optimizer specialist execution failed safely: %s",
                    type(error).__name__,
                )
                execution = None
        if execution is None:
            return AgentSubagentOutput(
                self.name,
                error_code="EXECUTION_FAILED",
                safe_metrics=embedding_usage.as_metrics(),
            )
        safe_execution = _mask_strings(execution.contribution, self._masker)
        if not isinstance(safe_execution, dict):
            return AgentSubagentOutput(
                self.name,
                error_code="EXECUTION_INVALID",
                safe_metrics=embedding_usage.as_metrics(),
            )
        safe_payload["execution"] = safe_execution
        candidate_components = self._candidate_components(
            request, execution.contribution
        )
        return AgentSubagentOutput(
            subagent=self.name,
            contribution=safe_payload,
            verification_status=execution.status,
            safe_metrics={**execution.safe_metrics, **embedding_usage.as_metrics()},
            error_code=execution.error_code,
            experiment_candidate_components=candidate_components,
        )

    def _candidate_components(
        self, request: AgentSubagentInput, execution: dict[str, Any]
    ) -> tuple[ComponentVersionReference, ...]:
        if self._component_resolver is None or not request.baseline_components:
            return ()
        candidates = {item.component: item for item in request.baseline_components}
        component, entity_id, version = {
            "configuration": (
                "configuration",
                execution.get("candidate_configuration_id"),
                execution.get("candidate_configuration_version"),
            ),
            "xgboost": (
                "model",
                execution.get("candidate_model_id"),
                execution.get("candidate_model_tag"),
            ),
            # A vector-store pin's version is its generation number.
            "vector_store": (
                "vector_store",
                execution.get("candidate_instance_id"),
                execution.get("candidate_generation"),
            ),
        }.get(self.name, ("", None, None))
        if not component or entity_id is None or version is None:
            return ()
        pin = self._component_resolver.pin(component, str(entity_id), str(version))
        if pin is None:
            return ()
        candidates[component] = pin
        if candidates[component] == next(
            (
                item
                for item in request.baseline_components
                if item.component == component
            ),
            None,
        ):
            return ()
        if set(candidates) != {"model", "configuration", "library", "vector_store"}:
            return ()
        return tuple(candidates[key] for key in sorted(candidates))


def _mask_strings(value: Any, masker: PersonalDataMasker) -> Any:
    if isinstance(value, str):
        return masker.mask(value).text
    if isinstance(value, list):
        return [_mask_strings(item, masker) for item in value]
    if isinstance(value, dict):
        return {
            masker.mask(str(key)).text: _mask_strings(item, masker)
            for key, item in value.items()
            if str(key).lower() not in {"customer_id", "case_id", "row_id"}
        }
    return value


def _objective_context(request: AgentSubagentInput) -> dict[str, Any] | None:
    objective = request.objective
    if objective is None:
        return None
    return {
        "objective_id": objective.objective_id,
        "version": objective.version,
        "success_label": objective.success_label,
        "positive_label": objective.positive_label,
        "negative_label": objective.negative_label,
        "primary_metrics": list(objective.primary_metrics),
        "precision_floor": objective.precision_floor,
        "minimum_support_per_segment": objective.minimum_support_per_segment,
        "minimum_global_support": objective.minimum_global_support,
        "minimum_mature_alert_coverage_pct": (
            objective.minimum_mature_alert_coverage_pct
        ),
        "unlabeled_rule": objective.unlabeled_rule,
        "schema_mapping": objective.schema_mapping,
    }


def _json_safe_default(value: Any) -> Any:
    """Normalize DynamoDB/runtime scalar types without stringifying numbers."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"Unsupported specialist context type: {type(value).__name__}")


def _strip_json_fence(raw: str) -> str:
    marker = chr(96) * 3
    value = raw.strip()
    if value.startswith(marker) and value.endswith(marker):
        value = value[len(marker) : -len(marker)].strip()
        if value.startswith("json"):
            value = value[4:].strip()
    return value


_GENERATION_ATTEMPTS = 2
_CONTRACT_REMINDER = (
    "Tu respuesta anterior no cumplió el contrato. Responde solo un objeto "
    'JSON con "rationale" (texto) y "experiment" (objeto) válido para tu '
    "palanca, usando solo los campos y rangos permitidos."
)


def _valid_proposal(name: str, raw: Any) -> dict[str, Any] | None:
    try:
        payload = json.loads(_strip_json_fence(raw))
    except (ValueError, TypeError):
        return None
    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("experiment"), dict)
        or not isinstance(payload.get("rationale"), str)
        or not _is_valid_experiment(name, payload["experiment"])
    ):
        return None
    return payload


def _is_valid_experiment(name: str, experiment: dict[str, Any]) -> bool:
    if name == "configuration":
        changes = experiment.get("changes")
        return (
            isinstance(changes, list)
            and bool(changes)
            and all(
                isinstance(change, dict)
                and isinstance(change.get("path"), str)
                and "value" in change
                and not change["path"].startswith(
                    ("infra.", "operational.", "kill_switch")
                )
                for change in changes
            )
        )
    if name == "library":
        return (
            experiment.get("entity_type")
            in {"modus_operandi", "taxonomy", "similar_case", "watchlist"}
            and isinstance(experiment.get("draft"), dict)
            and bool(experiment["draft"])
            and isinstance(experiment.get("evidence_summary"), str)
        )
    if name == "vector_store":
        return (
            isinstance(experiment.get("manifest_version"), int)
            and experiment["manifest_version"] > 0
            and isinstance(experiment.get("authorized_queries"), list)
            and bool(experiment["authorized_queries"])
            and all(
                isinstance(query, str) and query
                for query in experiment["authorized_queries"]
            )
        )
    if name == "xgboost":
        parameters = experiment.get("parameters")
        if not isinstance(parameters, dict):
            return False
        bounds = {
            "n_estimators": (1, 2000),
            "max_depth": (1, 16),
            "learning_rate": (0.001, 0.5),
            "subsample": (0.1, 1.0),
            "colsample_bytree": (0.1, 1.0),
        }
        return bool(parameters) and all(
            key in bounds
            and isinstance(value, (int, float))
            and bounds[key][0] <= value <= bounds[key][1]
            for key, value in parameters.items()
        )
    return False
