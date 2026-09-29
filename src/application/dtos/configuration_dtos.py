from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.application.ports.configuration_port import (
    GeneralSettings,
    InfraSettings,
    SegmentSettings,
    TestSettings,
    default_segments,
)


@dataclass
class CreateConfigurationInput:
    name: str
    # None -> new lineage (fresh configuration_id, version 1). Set -> new
    # version appended to that lineage's existing configuration_id.
    configuration_id: str | None = None
    # Optimistic-concurrency guard: the version the caller's draft was
    # seeded from. If set and it no longer matches the lineage's latest
    # version, CreateConfigurationUseCase raises instead of silently
    # overwriting a version the caller never saw.
    based_on_version: int | None = None
    description: str = ""
    general: GeneralSettings = field(default_factory=GeneralSettings)
    infra: InfraSettings = field(default_factory=InfraSettings)
    test: TestSettings = field(default_factory=TestSettings)
    created_by: str | None = None
    segments: dict[str, SegmentSettings] = field(default_factory=default_segments)


@dataclass(frozen=True)
class ConfigurationChange:
    path: str
    previous: Any
    proposed: Any


@dataclass(frozen=True)
class ConfigurationPreviewOutput:
    changes: list[ConfigurationChange]
    warnings: list[str]

    @property
    def valid(self) -> bool:
        return True
