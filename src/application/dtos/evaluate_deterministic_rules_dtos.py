from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DeterministicRuleMatch:
    matched: bool
    rule_id: str | None = None
    variable: str | None = None
    decision: str | None = None
    aric_action: str | None = None
