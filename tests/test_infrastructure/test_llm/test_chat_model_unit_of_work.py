from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.application.ports.llm_unit_of_work_port import (
    LLMMessage,
    LLMMessageRole,
)
from src.application.ports.monitoring_port import (
    MonitoringPort,
    MonitoringSpan,
)
from src.infrastructure.llm.langchain._chat_model_unit_of_work import (
    LangchainChatModelUnitOfWork,
)


class RecordingSpan(MonitoringSpan):
    def __init__(self) -> None:
        self.inputs: list[dict[str, Any]] = []
        self.results: list[dict[str, Any]] = []
        self.metas: dict[str, Any] = {}
        self.error: str | None = None

    def write_input(self, data: dict[str, Any]) -> None:
        self.inputs.append(data)

    def write_result(self, data: dict[str, Any]) -> None:
        self.results.append(data)

    def write_inner_logs(self, entries) -> None:
        pass

    def write_operation_metas(self, metadata: dict[str, Any]) -> None:
        self.metas.update(metadata)

    def record_dependency(self, name, kind, metadata=None) -> None:
        pass

    def finish(self, error: str | None = None) -> None:
        self.error = error


class RecordingMonitoring(MonitoringPort):
    def __init__(self) -> None:
        self.spans: list[RecordingSpan] = []
        self.started: list[tuple[str, str, dict | None]] = []

    def start(self, operation_name, operation_type, metadata=None):
        self.started.append((operation_name, operation_type, metadata))
        span = RecordingSpan()
        self.spans.append(span)
        return span


@dataclass
class _FakeResponse:
    content: str
    response_metadata: dict[str, Any] = field(default_factory=dict)
    usage_metadata: dict[str, Any] = field(default_factory=dict)


class _FakeChatModel:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response
        self.received_messages = None

    def invoke(self, messages):
        self.received_messages = messages
        return self._response


def test_invoke_returns_result_and_instruments_monitoring():
    monitoring = RecordingMonitoring()
    fake_client = _FakeChatModel(
        _FakeResponse(
            content="Hello back",
            response_metadata={"finish_reason": "stop"},
            usage_metadata={"input_tokens": 10, "output_tokens": 4},
        )
    )
    uow = LangchainChatModelUnitOfWork(
        client=fake_client,
        monitoring=monitoring,
        operation_name="write_email",
        model="gpt-4o-mini",
        provider="azure_openai",
    )

    result = uow.invoke(
        [
            LLMMessage(role=LLMMessageRole.SYSTEM, content="be terse"),
            LLMMessage(role=LLMMessageRole.USER, content="hi"),
        ]
    )

    assert result.content == "Hello back"
    assert result.model == "gpt-4o-mini"
    assert result.finish_reason == "stop"
    assert result.input_tokens == 10
    assert result.output_tokens == 4
    assert len(fake_client.received_messages) == 2

    operation_name, operation_type, metadata = monitoring.started[0]
    assert operation_name == "write_email"
    assert operation_type == "llm"
    assert metadata["provider"] == "azure_openai"
    assert metadata["model"] == "gpt-4o-mini"

    span = monitoring.spans[0]
    assert span.inputs[0]["messages"][1] == {
        "role": "user",
        "content": "hi",
    }
    assert span.results[0]["content"] == "Hello back"
    assert span.metas["input_tokens"] == 10
    assert span.error is None


def test_finish_reason_falls_back_to_stop_reason_key():
    # Bedrock's response_metadata uses "stop_reason", not OpenAI's
    # "finish_reason" - both providers share this same invoke() path.
    monitoring = RecordingMonitoring()
    fake_client = _FakeChatModel(
        _FakeResponse(
            content="hi",
            response_metadata={"stop_reason": "end_turn"},
            usage_metadata={"input_tokens": 1, "output_tokens": 1},
        )
    )
    uow = LangchainChatModelUnitOfWork(
        client=fake_client,
        monitoring=monitoring,
        operation_name="classify",
        model="us.anthropic.claude-sonnet-4-6",
        provider="aws_bedrock",
    )

    result = uow.invoke([LLMMessage(role=LLMMessageRole.USER, content="hi")])

    assert result.finish_reason == "end_turn"
