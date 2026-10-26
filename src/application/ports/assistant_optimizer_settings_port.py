from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class AssistantOptimizerSettings:
    """Runtime settings for the assistant, optimizer, objective, and sampler."""

    # Assistant
    assistant_enabled: bool = True
    assistant_max_message_chars: int = 8_000
    assistant_max_messages_per_session: int = 100
    max_sessions_per_user: int = 5
    chat_retention_days: int = 730

    # Optimizer
    optimizer_enabled: bool = False
    # Agreed caps: two optimizer sessions, six experiments overall and up to
    # three independent experiments per session at the same time.
    optimizer_max_concurrent_sessions: int = 2
    optimizer_max_concurrent_runs: int = 6
    optimizer_max_parallel_experiments: int = 3
    optimizer_max_candidates_per_session: int = 10
    optimizer_session_budget_ceiling_tokens: int = 100_000
    optimizer_session_budget_ceiling_usd: float = 50.0
    optimizer_session_budget_ceiling_seconds: int = 43_200
    optimizer_budget_renewal_requires_approval: bool = True
    optimizer_max_budget_renewals: int = 0
    optimizer_iterations_without_improvement: int = 3
    optimizer_stop_on_critical_failure: bool = True

    # Objective and hard limits
    objective_precision_floor: float = 0.9
    objective_minimum_support_per_segment: int = 100
    objective_minimum_count_to_publish_aggregates: int = 20
    objective_minimum_mature_alert_coverage_pct: float = 80.0

    # Maturity window (owned by OperationalSettings; exposed here for the
    # unified settings contract and must not be persisted by this port).
    maturing_days: int = 4
    expected_coverage_pct: float = 98.0
    stable_months: int = 6

    # Data sampling
    sampler_enabled: bool = False
    sampler_period_trigger_enabled: bool = True
    sampler_period_trigger_interval_days: int = 7
    sampler_volume_trigger_enabled: bool = False
    sampler_statistical_trigger_enabled: bool = False
    sampler_statistical_trigger_threshold: float = 0.0
    sampler_cooldown_days: int = 7
    sampler_period_days: int = 30
    sampler_volume_threshold: int = 10_000
    sampler_error_margin_pct: float = 5.0
    sampler_confidence_pct: float = 95.0
    sampler_strata: tuple[str, ...] = ()
    sampler_minimum_per_stratum: int = 100
    sampler_fraud_oversampling_ratio: float = 1.0
    sampler_train_proportion: float = 0.6
    sampler_validation_proportion: float = 0.2
    sampler_test_proportion: float = 0.2
    sampler_seed_policy: str = "fixed_per_sample"
    sampler_max_retained_samples: int = 12
    sampler_compatible_schema_versions: tuple[str, ...] = ()


class AssistantOptimizerSettingsPort(ABC):
    """Read and persist the current assistant and optimizer settings."""

    @abstractmethod
    def get(self) -> AssistantOptimizerSettings:
        raise NotImplementedError

    @abstractmethod
    def update(
        self, settings: AssistantOptimizerSettings
    ) -> AssistantOptimizerSettings:
        raise NotImplementedError
