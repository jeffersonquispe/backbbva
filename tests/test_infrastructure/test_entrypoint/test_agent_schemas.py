from datetime import UTC, datetime, timedelta

from src.application.ports.agent_link_port import AgentLink
from src.application.ports.agent_session_port import AgentSession, AgentSessionStatus
from src.infrastructure.entrypoint.api.schemas.agent import (
    AgentLinkResponse,
    AgentSessionResponse,
)


def test_agent_link_response_serializes_domain_dataclass() -> None:
    link = AgentLink(
        session_id="session-1",
        source_type="message",
        source_id="message-1",
        relation="proposes",
        target_type="insight",
        target_id="insight-1",
        created_at=datetime(2026, 10, 19, tzinfo=UTC),
    )

    response = AgentLinkResponse.model_validate(link)

    assert response.source_id == "message-1"
    assert response.target_id == "insight-1"


def test_session_response_exposes_lease_state_without_owner():
    session = AgentSession(
        session_id="session-1",
        mode="optimization",
        status=AgentSessionStatus.ACTIVE,
        owner_id="user-1",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        lease_owner="worker-private-id",
        lease_expires_at=datetime.now(UTC) + timedelta(hours=1),
    )

    response = AgentSessionResponse.model_validate(session)

    assert response.lease.status == "ACTIVE"
    assert response.lease.heartbeat_at is None
    assert "lease_owner" not in response.model_dump()
    assert "worker-private-id" not in response.model_dump_json()


def test_session_response_reports_none_and_expired_lease_states():
    now = datetime.now(UTC)
    empty = AgentSession(
        session_id="session-none",
        mode="optimization",
        status=AgentSessionStatus.ACTIVE,
        owner_id="user-1",
        created_at=now,
        updated_at=now,
    )
    expired = AgentSession(
        session_id="session-expired",
        mode="optimization",
        status=AgentSessionStatus.ACTIVE,
        owner_id="user-1",
        created_at=now,
        updated_at=now,
        lease_owner="private-worker",
        lease_expires_at=now - timedelta(seconds=1),
    )

    assert AgentSessionResponse.model_validate(empty).lease.status == "NONE"
    expired_response = AgentSessionResponse.model_validate(expired)
    assert expired_response.lease.status == "EXPIRED"
    assert expired_response.lease.expires_at == expired.lease_expires_at
    assert expired_response.lease.heartbeat_at is None
