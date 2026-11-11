from __future__ import annotations

import logging

import pytest

from src.application.ports.llm_catalog_port import LLMCatalogPort
from src.application.ports.llm_unit_of_work_factory_port import LLMUnitOfWorkFactory
from src.application.ports.llm_unit_of_work_port import (
    LLMInvocationResult,
    LLMMessage,
    LLMMessageRole,
    LLMUnitOfWork,
)
from src.application.use_cases.llm.resolve_element_llm import ResolveElementLLM
from src.domain.llm.catalog import LLM_ELEMENTS, LLMCatalog, LLMCatalogEntry
from src.infrastructure.llm.catalog.element_llm import (
    ElementLLMUnitOfWorkFactory,
    _ActiveSelection,
)

CATALOG = LLMCatalog((LLMCatalogEntry("preciso", "gpt-big"),))
MESSAGES = [LLMMessage(LLMMessageRole.USER, "secret prompt text")]


class InMemoryLLMCatalog(LLMCatalogPort):
    def get(self) -> LLMCatalog:
        return CATALOG


class RecordingUnitOfWork(LLMUnitOfWork):
    def __init__(self, model: str, fail: bool) -> None:
        self.model, self.fail = model, fail

    def invoke(self, messages: list[LLMMessage]) -> LLMInvocationResult:
        if self.fail:
            raise TimeoutError("provider said: secret prompt text sk-123")
        return LLMInvocationResult(content="ok", model=self.model)


class RecordingLLMFactory(LLMUnitOfWorkFactory):
    def __init__(self, fail: bool = False) -> None:
        self.models: list[str] = []
        self.fail = fail

    def create(
        self, *, model, monitoring, operation_name, temperature=0.0, max_tokens=None
    ):
        self.models.append(model)
        return RecordingUnitOfWork(model, self.fail)


def _factory(inner, selection) -> ElementLLMUnitOfWorkFactory:
    catalog = InMemoryLLMCatalog()
    resolver = ResolveElementLLM(catalog, {e: f"default-{e}" for e in LLM_ELEMENTS})
    return ElementLLMUnitOfWorkFactory(
        inner,
        "judge",
        catalog,
        resolver,
        _ActiveSelection(lambda: selection) if selection is not None else None,
    )


def _create(factory: ElementLLMUnitOfWorkFactory, model: str = "default-judge"):
    return factory.create(model=model, monitoring=None, operation_name="op")  # type: ignore[arg-type]


def test_active_selection_replaces_the_default_deployment_on_each_call() -> None:
    inner = RecordingLLMFactory()
    selection: dict[str, str | None] = {}
    factory = _factory(inner, None)
    factory._selection = _ActiveSelection(lambda: selection)
    factory._selection._loaded_at = float("-inf")

    _create(factory)
    selection["judge"] = "preciso"
    factory._selection._loaded_at = float("-inf")  # TTL expired
    _create(factory)

    assert inner.models == ["default-judge", "gpt-big"]


def test_without_following_the_selection_the_callers_model_is_kept() -> None:
    inner = RecordingLLMFactory()
    _create(_factory(inner, None), model="resolved-by-the-step")
    assert inner.models == ["resolved-by-the-step"]


def test_failure_is_logged_with_element_name_deployment_and_code_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    factory = _factory(RecordingLLMFactory(fail=True), {"judge": "preciso"})
    unit = _create(factory)

    with caplog.at_level(logging.ERROR), pytest.raises(TimeoutError):
        unit.invoke(MESSAGES)

    text = caplog.text
    assert "element=judge" in text and "name=preciso" in text
    assert "deployment=gpt-big" in text and "error_code=TimeoutError" in text
    assert "secret prompt text" not in text and "sk-123" not in text


def test_success_path_logs_nothing(caplog: pytest.LogCaptureFixture) -> None:
    unit = _create(_factory(RecordingLLMFactory(), {"judge": "preciso"}))
    with caplog.at_level(logging.DEBUG):
        assert unit.invoke(MESSAGES).content == "ok"
    assert caplog.text == ""


def test_unreadable_selection_falls_back_to_defaults(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def broken():
        raise RuntimeError("dynamo down")

    inner = RecordingLLMFactory()
    factory = _factory(inner, None)
    factory._selection = _ActiveSelection(broken)
    with caplog.at_level(logging.WARNING):
        _create(factory)
    assert inner.models == ["default-judge"]
