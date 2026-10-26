"""Intake-side workflow steps: pre_process, deterministic rules, profiling,
and the context enrichment (configuration/segment, rubrics) around them."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from src.application.dtos.evaluate_deterministic_rules_dtos import (
    DeterministicRuleMatch,
)
from src.application.dtos.pre_process_dtos import (
    PreProcessAlertInput,
    PreProcessAlertOutput,
)
from src.application.dtos.profile_alert_dtos import (
    ProfileAlertInput,
    ProfileAlertOutput,
)
from src.application.use_cases.alerts.alert_review_policy import active_segment
from src.domain.alerts.entities import (
    AlertOrigin,
)
from src.domain.alerts.rule_conditions import evaluate_condition
from src.domain.configurations.entities import (
    ProfilingStrategyKey,
)
from src.domain.configurations.exceptions import ConfigurationNotFoundError
from src.domain.models.prompt_template import substitute_variables
from src.infrastructure.workflows.celery.factories import (
    get_alert_schema_repository,
    get_configuration_repository,
    get_evaluate_deterministic_rules_use_case,
    get_pre_process_alert_use_case,
    get_profile_alert_use_case,
)
from src.infrastructure.workflows.celery.step_context import (
    _pre_process_comparison_value,
    _step_overrides,
    _step_reporting_ids,
    _variables_pool,
)
from src.infrastructure.workflows.celery.task_factories import (
    get_resolve_alert_segment_use_case,
)


def _skip_external_enrichment(origin: str | None) -> bool:
    return origin in {
        AlertOrigin.TEST_RUN.value,
        AlertOrigin.OPTIMIZER_EVALUATION.value,
        AlertOrigin.SIMULATOR.value,
    }


def _run_pre_process(context: dict[str, Any]) -> PreProcessAlertOutput:
    workflow_input = context.get("input") or {}
    payload = (
        workflow_input["alert_payload"]
        if "alert_payload" in workflow_input
        else context.get("raw_payload")
    ) or {}
    workflow_execution_id, step_id = _step_reporting_ids(context)
    use_case = get_pre_process_alert_use_case(
        status_reporter=context.get("status_reporter"),
        workflow_execution_id=workflow_execution_id,
        step_id=step_id,
    )
    candidate_version = workflow_input.get("schema_version")
    candidate_schema = (
        get_alert_schema_repository().get(int(candidate_version))
        if candidate_version is not None
        else None
    )
    candidate = use_case.execute(
        PreProcessAlertInput(
            alert_id=UUID(context["alert_id"]),
            payload=payload,
            schema=candidate_schema,
            skip_external_enrichment=_skip_external_enrichment(
                workflow_input.get("origin")
            ),
            origin=(
                AlertOrigin(workflow_input["origin"])
                if workflow_input.get("origin")
                else None
            ),
        )
    )
    if workflow_input.get("origin") not in {
        AlertOrigin.TEST_RUN.value,
        AlertOrigin.OPTIMIZER_EVALUATION.value,
    }:
        return candidate
    # With no pin the candidate was already produced from the active schema;
    # avoid a second repository read and preserve the single pre-process pass.
    active_schema_version = workflow_input.get("active_schema_version")
    schema_repository = get_alert_schema_repository()
    active_schema = (
        schema_repository.get(int(active_schema_version))
        if active_schema_version is not None
        else schema_repository.get_active()
    )
    if candidate_version is None or (
        active_schema is not None and active_schema.version == candidate.schema_version
    ):
        active = candidate
    else:
        active = get_pre_process_alert_use_case(
            status_reporter=None, workflow_execution_id=None, step_id=None
        ).execute(
            PreProcessAlertInput(
                alert_id=UUID(context["alert_id"]),
                payload=payload,
                schema=active_schema,
                skip_external_enrichment=_skip_external_enrichment(
                    workflow_input.get("origin")
                ),
                origin=(
                    AlertOrigin(workflow_input["origin"])
                    if workflow_input.get("origin")
                    else None
                ),
            )
        )
    context["schema_comparison"] = {
        "active": _pre_process_comparison_value(active),
        "candidate": _pre_process_comparison_value(candidate),
    }
    return candidate


def _run_deterministic(context: dict[str, Any]) -> DeterministicRuleMatch:
    segment = active_segment(context)
    if segment is None:
        return DeterministicRuleMatch(matched=False)
    deterministic_cfg = segment.agent.deterministic
    pre_process: PreProcessAlertOutput = context["pre_process"]
    fields = pre_process.input
    return get_evaluate_deterministic_rules_use_case().execute(
        deterministic_cfg.rules, fields, alert_filter=deterministic_cfg.alert_filter
    )


_PROFILING_STRATEGY_OPERATION_MAP = {
    ProfilingStrategyKey.USUARIO: "user_profile",
    ProfilingStrategyKey.TRANSACCION: "transaction_profile",
    ProfilingStrategyKey.TRANSACCIONAL: "transactional_profile",
}


def _run_profiling(context: dict[str, Any]) -> ProfileAlertOutput:
    workflow_execution_id, step_id = _step_reporting_ids(context)
    overrides = _step_overrides(context, "profiling")
    segment_kwargs: dict[str, Any] = {}
    if not overrides.get("system_prompt"):
        segment = active_segment(context)
        if segment is not None:
            variables_pool = _variables_pool(context, segment)
            extra_instructions = {
                _PROFILING_STRATEGY_OPERATION_MAP[s.key]: substitute_variables(
                    s.main_prompt, variables_pool
                )
                for s in segment.agent.profiling.strategies
                if s.main_prompt and s.key in _PROFILING_STRATEGY_OPERATION_MAP
            }
            if extra_instructions:
                segment_kwargs["extra_instructions"] = extra_instructions
    use_case = get_profile_alert_use_case(
        status_reporter=context.get("status_reporter"),
        workflow_execution_id=workflow_execution_id,
        step_id=step_id,
        **overrides,
        **segment_kwargs,
    )
    return use_case.execute(
        ProfileAlertInput(
            alert_id=UUID(context["alert_id"]),
            pre_process=context["pre_process"],
        )
    )


def _resolve_configuration(context: dict[str, Any]):
    # A test run can pin an exact (possibly inactive) ConfigurationRecord
    # via configuration_ref, instead of the implicit get_active() - see
    # ConfigurationRef (configuration_port.py) and TestRunConfig
    # (domain/test_runs/entities.py). Unlike the no-ref path below, an explicit ref
    # that doesn't resolve must raise: silently falling back to whatever
    # is currently active would corrupt the meaning of the test, and the
    # caller (the outer Celery task) is expected to surface this as a
    # failed workflow, not a misleadingly "successful" one run against
    # the wrong config.
    ref = (context.get("input") or {}).get("configuration_ref")
    repo = get_configuration_repository()
    if ref:
        configuration_id = ref["configuration_id"]
        version = ref.get("version")
        config = (
            repo.get(configuration_id, version)
            if version is not None
            else repo.get_latest_version(configuration_id)
        )
        if config is None:
            raise ConfigurationNotFoundError(configuration_id, version)
        return config
    try:
        return repo.get_active()
    except Exception:  # noqa: BLE001 - optional configuration enrichment is fail-safe
        return None


def _resolve_segment(context: dict[str, Any]) -> dict[str, Any]:
    # Context enrichment, not a persisted workflow step - must fail safe to
    # "no segment" (None) and never break existing behavior when there's no
    # active configuration or nothing matches. The one exception is an
    # explicit configuration_ref that fails to resolve - see
    # _resolve_configuration.
    config = _resolve_configuration(context)
    context["active_configuration"] = config
    context["segment_code"] = None
    if config is None:
        return context
    try:
        pre_process: PreProcessAlertOutput = context["pre_process"]
        context["segment_code"] = get_resolve_alert_segment_use_case().execute(
            input_fields=pre_process.input,
            segments=config.segments,
            roles=pre_process.roles,
        )
    except Exception:  # noqa: BLE001 - optional segment enrichment is fail-safe
        context["segment_code"] = None
    return context


def _run_rubrics(context: dict[str, Any]) -> dict[str, Any]:
    """Score every segment rubric against enriched alert fields.

    Additive scorecard: each matched condition adds its points to its
    rubric's score. Condition points of a rubric sum to 100 (enforced on
    save, see CreateConfigurationRequest), so each score is 0-100.
    """
    segment = active_segment(context)
    if segment is None:
        return {"scores": [], "evaluated": 0}
    fields = _variables_pool(context, segment)
    scores: list[dict[str, Any]] = []
    for rubric in segment.agent.rubrics:
        matched = [
            condition
            for condition in rubric.conditions
            if evaluate_condition(condition, fields)
        ]
        scores.append(
            {
                "id": rubric.id,
                "name": rubric.name,
                "score": sum(condition.score for condition in matched),
                "max_score": sum(condition.score for condition in rubric.conditions),
                "matched_condition_ids": [condition.id for condition in matched],
            }
        )
    return {"scores": scores, "evaluated": len(scores)}
