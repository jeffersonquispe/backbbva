"""Contracts for bounded, delegated alert research.

The primary alert agent never gets a dataframe nor a search client.  It asks
for research and receives a compact, auditable result instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ResearchSource(StrEnum):
    VECTOR_STORE = "vector_store"
    HISTORY_PANDAS = "history_pandas"


class ResearchStatus(StrEnum):
    EXECUTED = "executed"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(frozen=True)
class ResearchRequest:
    source: ResearchSource
    question: str
    alert_context: dict[str, Any] = field(default_factory=dict)
    prior_evidence: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class ResearchFinding:
    metric: str
    value: Any
    evidence: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ResearchResult:
    source: ResearchSource
    status: ResearchStatus
    findings: list[ResearchFinding] = field(default_factory=list)
    trace: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None


@dataclass(frozen=True)
class HistoryOperation:
    """A declarative dataframe operation; arbitrary Python is never accepted."""

    name: str
    column: str | None = None
    group_by: str | None = None
    operator: str | None = None
    value: Any = None
    aggregate: str | None = None
    current_value: Any = None
