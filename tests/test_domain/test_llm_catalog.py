from __future__ import annotations

import pytest

from src.domain.llm.catalog import (
    LLM_ELEMENTS,
    UNKNOWN_ELEMENT_CODE,
    UNKNOWN_NAME_CODE,
    InvalidLLMCatalogError,
    LLMCatalog,
    LLMCatalogEntry,
    LLMSelectionError,
    parse_llm_catalog,
    validate_llm_selection,
)

RAW = '[{"nombre": "rapido", "deployment": "gpt-fast"}, {"nombre": "preciso", "deployment": "gpt-big"}]'


def test_parse_reads_names_and_deployments() -> None:
    catalog = parse_llm_catalog(RAW)
    assert catalog.names == ("rapido", "preciso")
    assert catalog.get("preciso") == LLMCatalogEntry("preciso", "gpt-big")


def test_empty_value_means_no_catalog() -> None:
    assert parse_llm_catalog("  ").entries == ()


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        '{"nombre": "x"}',
        '["x"]',
        '[{"nombre": "x"}]',
        '[{"nombre": "", "deployment": "d"}]',
        '[{"nombre": "x", "deployment": " "}]',
        '[{"nombre": "x", "deployment": "a"}, {"nombre": "x", "deployment": "b"}]',
    ],
)
def test_invalid_catalog_is_rejected(raw: str) -> None:
    with pytest.raises(InvalidLLMCatalogError):
        parse_llm_catalog(raw)


def test_duplicate_names_are_rejected_on_the_entity() -> None:
    with pytest.raises(InvalidLLMCatalogError):
        LLMCatalog((LLMCatalogEntry("a", "x"), LLMCatalogEntry("a", "y")))


def test_selection_accepts_known_names_and_blanks_to_none() -> None:
    catalog = parse_llm_catalog(RAW)
    cleaned = validate_llm_selection(
        {"judge": "preciso", "analyst": "", "report": None}, catalog
    )
    assert cleaned == {"judge": "preciso", "analyst": None, "report": None}


def test_selection_rejects_unknown_name_and_element() -> None:
    catalog = parse_llm_catalog(RAW)
    with pytest.raises(LLMSelectionError) as name_error:
        validate_llm_selection({"judge": "otro"}, catalog)
    assert name_error.value.error_code == UNKNOWN_NAME_CODE
    with pytest.raises(LLMSelectionError) as element_error:
        validate_llm_selection({"nope": "rapido"}, catalog)
    assert element_error.value.error_code == UNKNOWN_ELEMENT_CODE


def test_every_workflow_and_support_component_is_an_element() -> None:
    assert {"profiling", "executor", "judge", "assistant_chat", "optimizer"} <= set(
        LLM_ELEMENTS
    )
    assert len(set(LLM_ELEMENTS)) == len(LLM_ELEMENTS)
