from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol


class SamplingIntervalUnit(StrEnum):
    MINUTES = "minutes"
    HOURS = "hours"
    DAYS = "days"


class TestCleanupPolicy(StrEnum):
    MANUAL = "manual"
    OLDEST = "oldest"
    FAILED_FIRST = "failed-first"


class ShortageAction(StrEnum):
    BLOCK_SOFT = "block-soft"
    CUSTOM = "custom"


@dataclass
class Taxonomy:
    id: str
    code: str
    name: str
    description: str
    variables: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)
    active: bool = True
    segmento: str = ""


@dataclass
class ModusOperandi:
    # Belongs to (and is owned by) exactly one taxonomy.
    id: str
    title: str
    narrative: str
    taxonomy_id: str
    segmento: str = ""


@dataclass
class RedFlag:
    # Owned by a modus operandi; taxonomy_id is denormalized from the
    # parent modus operandi for filter convenience (mirrors
    # RedFlagDocument in fraud_knowledge_port.py, which does the same).
    id: str
    name: str
    description: str
    modus_operandi_id: str
    taxonomy_id: str
    variables: list[str] = field(default_factory=list)
    segmento: str = ""


@dataclass
class YellowFlag:
    id: str
    name: str
    description: str
    modus_operandi_id: str
    taxonomy_id: str
    variables: list[str] = field(default_factory=list)
    segmento: str = ""


@dataclass
class ExampleCase:
    # Belongs to both a modus operandi and (denormalized) its taxonomy at
    # once - mirrors SimilarCaseDocument in fraud_knowledge_port.py.
    id: str
    text: str
    modus_operandi_id: str
    taxonomy_id: str
    segmento: str = ""


@dataclass
class DistributionValue:
    id: str
    label: str
    pct: int


@dataclass
class SamplingCriterion:
    id: str
    name: str
    values: list[DistributionValue] = field(default_factory=list)


@dataclass
class DayProfile:
    id: str
    name: str
    description: str
    hourly: list[int] = field(default_factory=lambda: [0] * 24)


def _default_analyst_profiles() -> list[DayProfile]:
    return [
        DayProfile(
            id="regular",
            name="Día regular",
            description="Cobertura estándar para días hábiles sin eventos especiales.",
            hourly=[4] * 24,
        ),
        DayProfile(
            id="pago",
            name="Día de pago",
            description="Refuerzo por mayor volumen de alertas en fechas de pago.",
            hourly=[8] * 24,
        ),
    ]


@dataclass
class AnalystCapacity:
    profiles: list[DayProfile] = field(default_factory=_default_analyst_profiles)
    default_profile_id: str = "regular"
    day_overrides: dict[int, str] = field(
        default_factory=lambda: {15: "pago", 20: "pago", 30: "pago"}
    )


@dataclass
class ShortageBehavior:
    action: ShortageAction = ShortageAction.BLOCK_SOFT
    custom_text: str = ""


@dataclass
class GeneralSettings:
    agent_enabled: bool = True
    migration_window_enabled: bool = False
    # Hour of day, 0-23 (see schemas.GeneralSettingsSchema for the ge/le
    # validation - the dataclass itself doesn't enforce it).
    migration_window_hour: int = 2


@dataclass
class InfraSettings:
    max_instances: int = 8
    auto_scale: bool = True


@dataclass
class OpsSettings:
    voicebot_max_concurrent_calls: int = 40
    analyst_capacity: AnalystCapacity = field(default_factory=AnalystCapacity)
    queue_max_lifetime_value: int = 60
    queue_max_lifetime_unit: SamplingIntervalUnit = SamplingIntervalUnit.MINUTES
    voicebot_shortage_behavior: ShortageBehavior = field(
        default_factory=ShortageBehavior
    )
    analyst_shortage_behavior: ShortageBehavior = field(
        default_factory=ShortageBehavior
    )


@dataclass
class MonitoringSettings:
    sampling_interval_value: int = 30
    sampling_interval_unit: SamplingIntervalUnit = SamplingIntervalUnit.MINUTES
    sampling_criteria: list[SamplingCriterion] = field(default_factory=list)
    max_samples: int = 200
    prompt_clasificacion: str = ""
    prompt_analista: str = ""
    prompt_monitoreo: str = ""
    evaluation_variables: list[str] = field(default_factory=list)


@dataclass
class AgentSettings:
    perfil_usuario: str = ""
    perfil_usuario_vars: list[str] = field(default_factory=list)
    perfil_transaccion: str = ""
    perfil_transaccion_vars: list[str] = field(default_factory=list)
    perfil_transaccional: str = ""
    perfil_transaccional_vars: list[str] = field(default_factory=list)
    taxonomies: list[Taxonomy] = field(default_factory=list)
    modus_operandi: list[ModusOperandi] = field(default_factory=list)
    red_flags: list[RedFlag] = field(default_factory=list)
    yellow_flags: list[YellowFlag] = field(default_factory=list)
    example_cases: list[ExampleCase] = field(default_factory=list)
    active_fields: list[str] = field(default_factory=list)


@dataclass
class TestSettings:
    max_test_instances: int = 4
    max_concurrent_experiments: int = 3
    experiment_timeout_minutes: int = 30
    max_stored_test_runs: int = 20
    test_cleanup_policy: TestCleanupPolicy = TestCleanupPolicy.OLDEST


@dataclass
class ConfigurationRecord:
    # Stable id shared across every version of the same named configuration
    # ("lineage") - distinct from `version`, which increments per edit.
    configuration_id: str
    version: int
    name: str
    description: str
    active: bool
    general: GeneralSettings
    infra: InfraSettings
    ops: OpsSettings
    monitoring: MonitoringSettings
    agent: AgentSettings
    test: TestSettings
    created_at: datetime
    updated_at: datetime
    created_by: str | None = None


class ConfigurationRepository(Protocol):
    def create(self, config: ConfigurationRecord) -> ConfigurationRecord:
        ...

    def get(
        self, configuration_id: str, version: int
    ) -> ConfigurationRecord | None:
        ...

    def get_latest_version(
        self, configuration_id: str
    ) -> ConfigurationRecord | None:
        ...

    def get_active(self) -> ConfigurationRecord | None:
        ...

    def list_latest(self) -> list[ConfigurationRecord]:
        ...

    def list_versions(self, configuration_id: str) -> list[ConfigurationRecord]:
        ...

    def activate(self, configuration_id: str, version: int) -> ConfigurationRecord:
        ...
