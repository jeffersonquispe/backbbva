from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MatureSamplePreview:
    eligible_alerts: int
    estimated_sample_size: int
    counts_by_stratum: dict[str, int]
    active_triggers: list[str]
