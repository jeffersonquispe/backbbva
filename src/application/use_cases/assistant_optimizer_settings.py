from __future__ import annotations

from dataclasses import fields, replace
from typing import Any

from src.application.errors import ValidationError
from src.application.ports.assistant_optimizer_settings_changes_port import (
    AssistantOptimizerSettingChange,
    AssistantOptimizerSettingsChange,
    AssistantOptimizerSettingsChangesPort,
)
from src.application.ports.assistant_optimizer_settings_port import (
    AssistantOptimizerSettings,
    AssistantOptimizerSettingsPort,
)
from src.application.ports.audit_port import AuditEntry, AuditPort
from src.application.ports.clock_port import Clock
from src.application.ports.id_generator_port import IdGenerator
from src.application.runtime_defaults import DEFAULT_ID_GENERATOR, resolve_clock

_NON_PERSISTED_FIELDS = {"maturing_days", "expected_coverage_pct", "stable_months"}


class GetAssistantOptimizerSettingsUseCase:
    def __init__(self, settings: AssistantOptimizerSettingsPort) -> None:
        self._settings = settings

    def execute(self) -> AssistantOptimizerSettings:
        current = self._settings.get()
        return replace(
            current,
            **{
                name: getattr(AssistantOptimizerSettings(), name)
                for name in _NON_PERSISTED_FIELDS
            },
        )


class UpdateAssistantOptimizerSettingsUseCase:
    def __init__(
        self,
        settings: AssistantOptimizerSettingsPort,
        changes: AssistantOptimizerSettingsChangesPort,
        audit: AuditPort,
        clock: Clock | None = None,
        id_generator: IdGenerator | None = None,
    ) -> None:
        self._settings = settings
        self._changes = changes
        self._audit = audit
        self._clock = resolve_clock(clock)
        self._id_generator = id_generator or DEFAULT_ID_GENERATOR

    def execute(
        self, proposed: AssistantOptimizerSettings, changed_by: str
    ) -> AssistantOptimizerSettings:
        _validate(proposed)
        current = self._settings.get()
        # The maturity values belong to OperationalSettings, not this singleton.
        proposed = replace(
            proposed,
            maturing_days=current.maturing_days,
            expected_coverage_pct=current.expected_coverage_pct,
            stable_months=current.stable_months,
        )
        changes = _diff(_persisted_values(current), _persisted_values(proposed))
        updated = self._settings.update(proposed)
        if not changes:
            return updated
        now = self._clock.now()
        change_id = str(self._id_generator.new_id())
        change = AssistantOptimizerSettingsChange(
            id=change_id, changed_by=changed_by, changed_at=now, changes=changes
        )
        self._changes.append(change)
        self._audit.write(
            AuditEntry(
                actor_type="user",
                actor_id=changed_by,
                worker_name=None,
                action="assistant_optimizer_settings.update",
                entity_type="assistant_optimizer_settings",
                entity_id="current",
                correlation_id=change_id,
                parent_id=None,
                occurred_at=now,
                outcome="success",
            )
        )
        return updated


class ListAssistantOptimizerSettingsChangesUseCase:
    def __init__(self, changes: AssistantOptimizerSettingsChangesPort) -> None:
        self._changes = changes

    def execute(self, limit: int = 50) -> list[AssistantOptimizerSettingsChange]:
        return self._changes.list(max(1, min(limit, 100)))


def _persisted_values(settings: AssistantOptimizerSettings) -> dict[str, Any]:
    return {
        field.name: value
        for field in fields(settings)
        if field.name not in _NON_PERSISTED_FIELDS
        for value in (getattr(settings, field.name),)
    }


def _diff(
    previous: dict[str, Any], new: dict[str, Any]
) -> list[AssistantOptimizerSettingChange]:
    return [
        AssistantOptimizerSettingChange(path=key, previous=previous[key], new=new[key])
        for key in sorted(previous)
        if previous[key] != new[key]
    ]


def _validate(settings: AssistantOptimizerSettings) -> None:
    bounded_ints = {
        "assistant_max_message_chars": (1, 8_000),
        "assistant_max_messages_per_session": (1, 1_000),
        "max_sessions_per_user": (1, 100),
        "chat_retention_days": (1, 730),
        "optimizer_max_concurrent_sessions": (1, 100),
        "optimizer_max_concurrent_runs": (1, 100),
        "optimizer_max_parallel_experiments": (1, 10),
        "optimizer_max_candidates_per_session": (1, 100),
        "optimizer_session_budget_ceiling_tokens": (1, 10_000_000),
        "optimizer_session_budget_ceiling_seconds": (1, 604_800),
        "optimizer_max_budget_renewals": (0, 100),
        "optimizer_iterations_without_improvement": (1, 100),
        "optimizer_max_retryable_failures": (0, 10),
        "objective_minimum_support_per_segment": (1, 10_000_000),
        "objective_minimum_count_to_publish_aggregates": (1, 1_000_000),
        "sampler_period_trigger_interval_days": (1, 365),
        "sampler_cooldown_days": (0, 365),
        "sampler_period_days": (1, 365),
        "sampler_volume_threshold": (1, 100_000_000),
        "sampler_minimum_per_stratum": (1, 1_000_000),
        "sampler_max_retained_samples": (1, 120),
    }
    for name, (minimum, maximum) in bounded_ints.items():
        value = getattr(settings, name)
        if isinstance(value, bool) or not minimum <= value <= maximum:
            raise ValidationError(f"{name} debe estar entre {minimum} y {maximum}")
    bounded_floats = {
        "optimizer_session_budget_ceiling_usd": (0.01, 1_000_000.0),
        "objective_precision_floor": (0.0, 1.0),
        "objective_minimum_mature_alert_coverage_pct": (0.0, 100.0),
        "sampler_statistical_trigger_threshold": (0.0, 1.0),
        "sampler_error_margin_pct": (0.1, 50.0),
        "sampler_confidence_pct": (50.0, 99.9),
        "sampler_fraud_oversampling_ratio": (1.0, 100.0),
    }
    for float_name, (min_float, max_float) in bounded_floats.items():
        float_value = getattr(settings, float_name)
        if isinstance(float_value, bool) or not min_float <= float_value <= max_float:
            raise ValidationError(
                f"{float_name} debe estar entre {min_float} y {max_float}"
            )
    proportions = (
        settings.sampler_train_proportion,
        settings.sampler_validation_proportion,
        settings.sampler_test_proportion,
    )
    if (
        any(not 0 < value < 1 for value in proportions)
        or abs(sum(proportions) - 1) > 1e-6
    ):
        raise ValidationError(
            "Las proporciones de train, validation y test deben sumar 1"
        )
    if settings.sampler_seed_policy not in {"fixed_per_sample", "random_per_sample"}:
        raise ValidationError("sampler_seed_policy no es válido")
    if (
        len(settings.sampler_strata) > 50
        or len(settings.sampler_compatible_schema_versions) > 50
    ):
        raise ValidationError("La lista no puede superar 50 elementos")
    if any(
        not value.strip()
        for value in (
            *settings.sampler_strata,
            *settings.sampler_compatible_schema_versions,
        )
    ):
        raise ValidationError("Las listas no pueden incluir valores vacíos")
