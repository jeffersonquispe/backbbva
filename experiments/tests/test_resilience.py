import pytest
from botocore.exceptions import ClientError
from pydantic import BaseModel, ValidationError

from agents._resilience import invoke_with_retry


class _DummySchema(BaseModel):
    campo_requerido: str


class _FakeStructuredLLM:
    def __init__(self, fail_times, exc_factory):
        self.calls = 0
        self.fail_times = fail_times
        self.exc_factory = exc_factory

    def invoke(self, messages):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc_factory()
        return "OK"


def _throttling_error():
    return ClientError({"Error": {"Code": "ThrottlingException", "Message": "x"}}, "InvokeModel")


def _empty_tool_call_validation_error():
    # Reproduce el caso real reportado: el modelo no invoca el schema y
    # LangChain termina validando un dict vacío -> ValidationError con todos
    # los campos "Field required [type=missing]".
    try:
        _DummySchema.model_validate({})
    except ValidationError as e:
        return e


def _non_retryable_error():
    return RuntimeError("algo inesperado y no relacionado con Bedrock")


def test_retries_and_recovers_from_transient_throttling():
    llm = _FakeStructuredLLM(fail_times=2, exc_factory=_throttling_error)
    result = invoke_with_retry(llm, [], agent_name="Test", base_delay=0.01)
    assert result == "OK"
    assert llm.calls == 3


def test_retries_and_recovers_from_empty_structured_output():
    # Caso real: el Documentador recibía {} del LLM y fallaba con
    # ValidationError; ahora debe reintentar y recuperarse en el 2do intento.
    llm = _FakeStructuredLLM(fail_times=1, exc_factory=_empty_tool_call_validation_error)
    result = invoke_with_retry(llm, [], agent_name="Documentador", base_delay=0.01)
    assert result == "OK"
    assert llm.calls == 2


def test_non_retryable_error_propagates_on_first_attempt():
    llm = _FakeStructuredLLM(fail_times=99, exc_factory=_non_retryable_error)
    with pytest.raises(RuntimeError):
        invoke_with_retry(llm, [], agent_name="Test", base_delay=0.01)
    assert llm.calls == 1


def test_gives_up_after_max_retries_and_raises_last_error():
    llm = _FakeStructuredLLM(fail_times=99, exc_factory=_throttling_error)
    with pytest.raises(ClientError):
        invoke_with_retry(llm, [], agent_name="Test", max_retries=2, base_delay=0.01)
    assert llm.calls == 3


def test_gives_up_after_max_retries_on_persistent_validation_error():
    llm = _FakeStructuredLLM(fail_times=99, exc_factory=_empty_tool_call_validation_error)
    with pytest.raises(ValidationError):
        invoke_with_retry(llm, [], agent_name="Test", max_retries=2, base_delay=0.01)
    assert llm.calls == 3
