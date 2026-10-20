from datetime import UTC, datetime

from src.application.ports.agent_session_port import AgentSessionStatus
from src.infrastructure.persistence.database.dynamodb.repositories.agent_session_repository import (
    _from_item,
)


def test_session_budget_renewal_count_round_trips_and_defaults_for_legacy_rows():
    row = {
        "session_id": "session-1",
        "mode": "optimization",
        "status": AgentSessionStatus.PAUSED.value,
        "owner_id": "manager-1",
        "created_at": datetime(2026, 10, 20, tzinfo=UTC).isoformat(),
        "updated_at": datetime(2026, 10, 20, tzinfo=UTC).isoformat(),
        "budget_limits": {"tokens": 20},
        "budget_renewals": 2,
        "objective_id": "global_fraud_effectiveness",
        "objective_version": 5,
    }
    assert _from_item(row).budget_renewals == 2
    assert _from_item(row).objective_id == "global_fraud_effectiveness"
    assert _from_item(row).objective_version == 5
    assert _from_item({key: value for key, value in row.items() if key != "budget_renewals"}).budget_renewals == 0
    legacy = {
        key: value
        for key, value in row.items()
        if key not in {"budget_renewals", "objective_id", "objective_version"}
    }
    assert _from_item(legacy).objective_id is None
    assert _from_item(legacy).objective_version is None
