from __future__ import annotations

from dataclasses import dataclass, field

from src.application.ports.configuration_port import (
    AgentSettings,
    GeneralSettings,
    InfraSettings,
    MonitoringSettings,
    OpsSettings,
    TestSettings,
)


@dataclass
class CreateConfigurationInput:
    name: str
    # None -> new lineage (fresh configuration_id, version 1). Set -> new
    # version appended to that lineage's existing configuration_id.
    configuration_id: str | None = None
    description: str = ""
    general: GeneralSettings = field(default_factory=GeneralSettings)
    infra: InfraSettings = field(default_factory=InfraSettings)
    ops: OpsSettings = field(default_factory=OpsSettings)
    monitoring: MonitoringSettings = field(default_factory=MonitoringSettings)
    agent: AgentSettings = field(default_factory=AgentSettings)
    test: TestSettings = field(default_factory=TestSettings)
    created_by: str | None = None
