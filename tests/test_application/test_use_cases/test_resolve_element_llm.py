from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from src.application.ports.llm_catalog_port import LLMCatalogPort
from src.application.use_cases.llm.get_llm_catalog import GetLLMCatalogUseCase
from src.application.use_cases.llm.resolve_element_llm import (
    SOURCE_CONFIGURATION,
    SOURCE_DEFAULT,
    SOURCE_OVERRIDE,
    ResolveElementLLM,
)
from src.domain.llm.catalog import (
    LLM_ELEMENTS,
    UNKNOWN_ELEMENT_CODE,
    UNKNOWN_NAME_CODE,
    LLMCatalog,
    LLMCatalogEntry,
    LLMSelectionError,
)

CATALOG = LLMCatalog(
    (LLMCatalogEntry("rapido", "gpt-fast"), LLMCatalogEntry("preciso", "gpt-big"))
)
DEFAULTS = {element: f"default-{element}" for element in LLM_ELEMENTS}


class InMemoryLLMCatalog(LLMCatalogPort):
    def __init__(self, catalog: LLMCatalog) -> None:
        self._catalog = catalog

    def get(self) -> LLMCatalog:
        return self._catalog


def _resolver(catalog: LLMCatalog = CATALOG) -> ResolveElementLLM:
    return ResolveElementLLM(InMemoryLLMCatalog(catalog), DEFAULTS)


def test_default_when_nothing_selects_a_deployment() -> None:
    resolved = _resolver().execute("judge")
    assert (resolved.deployment, resolved.name, resolved.source) == (
        "default-judge",
        None,
        SOURCE_DEFAULT,
    )


def test_configuration_selection_beats_the_default() -> None:
    resolved = _resolver().execute("judge", selection={"judge": "preciso"})
    assert (resolved.deployment, resolved.name, resolved.source) == (
        "gpt-big",
        "preciso",
        SOURCE_CONFIGURATION,
    )


def test_selection_for_another_element_or_none_is_ignored() -> None:
    assert _resolver().execute("judge", selection={"analyst": "preciso"}).source == (
        SOURCE_DEFAULT
    )
    assert _resolver().execute("judge", selection={"judge": None}).source == (
        SOURCE_DEFAULT
    )


def test_test_override_beats_the_configuration() -> None:
    resolved = _resolver().execute(
        "analyst", override="rapido", selection={"analyst": "preciso"}
    )
    assert (resolved.deployment, resolved.name, resolved.source) == (
        "gpt-fast",
        "rapido",
        SOURCE_OVERRIDE,
    )


def test_name_outside_the_catalog_fails_with_a_clear_code() -> None:
    with pytest.raises(LLMSelectionError) as error:
        _resolver().execute("analyst", selection={"analyst": "borrado"})
    assert error.value.error_code == UNKNOWN_NAME_CODE
    with pytest.raises(LLMSelectionError) as override_error:
        _resolver().execute("analyst", override="borrado")
    assert override_error.value.error_code == UNKNOWN_NAME_CODE


def test_unknown_element_fails() -> None:
    with pytest.raises(LLMSelectionError) as error:
        _resolver().execute("nope")
    assert error.value.error_code == UNKNOWN_ELEMENT_CODE


def test_without_a_catalog_a_legacy_override_is_a_raw_deployment() -> None:
    resolved = _resolver(LLMCatalog()).execute("analyst", override="legacy-deployment")
    assert (resolved.deployment, resolved.name) == ("legacy-deployment", None)


@given(
    element=st.sampled_from(LLM_ELEMENTS),
    override=st.one_of(st.none(), st.sampled_from(CATALOG.names)),
    chosen=st.one_of(st.none(), st.sampled_from(CATALOG.names)),
)
def test_priority_is_override_then_selection_then_default(
    element: str, override: str | None, chosen: str | None
) -> None:
    resolved = _resolver().execute(
        element, override=override, selection={element: chosen}
    )
    expected = override or chosen
    if expected is None:
        assert resolved.deployment == DEFAULTS[element]
        assert resolved.name is None
    else:
        assert resolved.name == expected
        assert resolved.deployment == CATALOG.get(expected).deployment  # type: ignore[union-attr]


def test_catalog_use_case_lists_entries_groups_and_defaults() -> None:
    output = GetLLMCatalogUseCase(InMemoryLLMCatalog(CATALOG), _resolver()).execute()
    assert [e.name for e in output.entries] == ["rapido", "preciso"]
    by_element = {e.element: e for e in output.elements}
    assert set(by_element) == set(LLM_ELEMENTS)
    assert by_element["detector"].group == "workflow"
    assert by_element["judge"].group == "support"
    assert by_element["judge"].default_deployment == "default-judge"
