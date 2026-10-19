from datetime import UTC, datetime

from src.application.ports.agent_link_port import AgentLink
from src.infrastructure.entrypoint.api.schemas.agent import AgentLinkResponse


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
