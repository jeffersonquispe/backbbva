from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.application.ports.llm_catalog_port import LLMCatalogPort
from src.application.use_cases.llm.resolve_element_llm import ResolveElementLLM
from src.domain.llm.catalog import (
    LLM_ELEMENTS,
    UNKNOWN_NAME_CODE,
    LLMCatalog,
    LLMCatalogEntry,
    LLMSelectionError,
)
from src.infrastructure.workflows.celery import step_context


class InMemoryLLMCatalog(LLMCatalogPort):
    def get(self) -> LLMCatalog:
        return LLMCatalog(
            (
                LLMCatalogEntry("rapido", "gpt-fast"),
                LLMCatalogEntry("preciso", "gpt-big"),
            )
        )


@pytest.fixture(autouse=True)
def _resolver(monkeypatch: pytest.MonkeyPatch) -> None:
    resolver = ResolveElementLLM(
        InMemoryLLMCatalog(), {e: f"default-{e}" for e in LLM_ELEMENTS}
    )
    monkeypatch.setattr(step_context, "get_resolve_element_llm", lambda: resolver)


def _context(selection=None, overrides=None) -> dict:
    return {
        "input": {"config_overrides": {"model_overrides": overrides or {}}},
        "active_configuration": SimpleNamespace(
            general=SimpleNamespace(llm_selection=selection or {})
        ),
    }


def test_no_selection_leaves_the_step_on_its_own_default() -> None:
    context = _context()
    assert step_context._step_overrides(context, "analyst")["model"] is None
    assert context["llm_resolutions"]["analyst"]["source"] == "default"


def test_configuration_selection_sets_the_deployment_and_is_recorded() -> None:
    context = _context(selection={"analyst": "preciso"})
    assert step_context._step_overrides(context, "analyst")["model"] == "gpt-big"
    assert context["llm_resolutions"]["analyst"] == {
        "element": "analyst",
        "name": "preciso",
        "deployment": "gpt-big",
        "source": "configuration",
    }
    # Another step of the same run is untouched.
    assert step_context._step_overrides(context, "detector")["model"] is None


def test_test_override_beats_the_configuration_selection() -> None:
    context = _context(
        selection={"analyst": "preciso"}, overrides={"analyst": "rapido"}
    )
    assert step_context._step_overrides(context, "analyst")["model"] == "gpt-fast"


def test_run_without_configuration_uses_defaults() -> None:
    context = {"input": None}
    assert step_context._step_overrides(context, "profiling")["model"] is None


def test_selection_removed_from_the_catalog_fails_the_step_clearly() -> None:
    with pytest.raises(LLMSelectionError) as error:
        step_context._step_overrides(
            _context(selection={"analyst": "borrado"}), "analyst"
        )
    assert error.value.error_code == UNKNOWN_NAME_CODE
