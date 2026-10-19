from src.application.ports.agent_subagent_port import AgentSubagentInput
from src.infrastructure.agents.stub_subagent import StubAgentSubagent


def test_stub_subagent_returns_a_safe_contribution() -> None:
    result = StubAgentSubagent().execute(
        AgentSubagentInput(
            session_id="session-1",
            iteration_number=1,
            scope={"area": "library"},
            hypothesis="check the configured fallback",
            budget={"steps": 1},
        )
    )

    assert result.subagent == "stub"
    assert result.verification_status == "PASSED"
    assert result.contribution["hypothesis"] == "check the configured fallback"
    assert result.safe_metrics == {"steps": 1}


def test_stub_subagent_honors_cancellation() -> None:
    result = StubAgentSubagent().execute(
        AgentSubagentInput(
            session_id="session-1",
            iteration_number=1,
            scope={},
            hypothesis="",
            budget={},
            cancelled=True,
        )
    )

    assert result.verification_status == "CANCELLED"
    assert result.error_code == "RUN_CANCELLED"
