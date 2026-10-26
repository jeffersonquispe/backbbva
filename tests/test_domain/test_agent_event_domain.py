from datetime import UTC, datetime

import pytest

from src.domain.agents.event import (
    ALLOWED_REF_KEYS,
    AgentEvent,
    AgentEventKind,
    AgentEventOutcome,
    safe_refs,
)
from src.domain.agents.failure_catalog import (
    CATALOG,
    UNKNOWN_FAILURE,
    describe_failure,
)
from src.domain.agents.finding import (
    MIN_SUPPORT,
    OptimizerInsight,
    OptimizerInsightKind,
    OptimizerInsightStatus,
)

NOW = datetime(2026, 10, 26, tzinfo=UTC)


def test_safe_refs_drops_unknown_keys_and_none_values() -> None:
    refs = safe_refs(
        {
            "experiment_id": "e1",
            "customer_id": "c-77",
            "amount": 1500,
            "run_id": None,
            "iteration": 3,
        }
    )
    assert refs == {"experiment_id": "e1", "iteration": "3"}
    assert set(refs) <= ALLOWED_REF_KEYS


def test_every_blocking_approval_kind_is_known() -> None:
    assert {entry.approval for entry in CATALOG.values()} <= {
        None,
        "budget",
        "candidates",
        "context",
    }


def test_catalogue_entries_are_complete_spanish_copy() -> None:
    for entry in CATALOG.values():
        assert entry.title and entry.detail and entry.action, entry.code
        assert entry.code == entry.code.upper()


def test_blocks_wait_for_the_channel_manager_and_infra_failures_retry() -> None:
    assert describe_failure("BUDGET_EXHAUSTED").approval == "budget"
    assert describe_failure("CONTEXT_MISSING").approval == "context"
    assert describe_failure("CANDIDATE_LIMIT_REACHED").approval == "candidates"
    assert describe_failure("WORKER_LEASE_EXPIRED").retryable is True
    assert describe_failure("WORKER_LEASE_EXPIRED").approval is None


def test_unknown_or_raw_codes_never_leak() -> None:
    raw = "Traceback: KeyError customer 8812"
    assert describe_failure(raw) is UNKNOWN_FAILURE
    assert raw not in describe_failure(raw).detail
    assert describe_failure(None) is UNKNOWN_FAILURE


def test_event_is_immutable_value() -> None:
    event = AgentEvent(
        session_id="s1",
        seq=1,
        event_id="e",
        occurred_at=NOW,
        kind=AgentEventKind.SESSION,
        outcome=AgentEventOutcome.STARTED,
        summary="Sesión iniciada",
    )
    with pytest.raises(AttributeError):
        event.seq = 2  # type: ignore[misc]


def _insight(sample_count: int) -> OptimizerInsight:
    return OptimizerInsight(
        insight_id="i1",
        statement="Las alertas nocturnas de Digital tienen más falsos positivos",
        kind=OptimizerInsightKind.PATTERN,
        scope_key="channel:digital",
        status=OptimizerInsightStatus.SUPPORTED,
        sample_count=sample_count,
        created_at=NOW,
        last_evaluated_at=NOW,
        review_after=NOW,
    )


def test_optimizer_insight_requires_minimum_support() -> None:
    assert _insight(MIN_SUPPORT).sample_count == MIN_SUPPORT
    with pytest.raises(ValueError, match="INSIGHT_SUPPORT_TOO_LOW"):
        _insight(MIN_SUPPORT - 1)
