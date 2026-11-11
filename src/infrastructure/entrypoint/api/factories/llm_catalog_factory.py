from __future__ import annotations

from src.application.use_cases.llm.get_llm_catalog import GetLLMCatalogUseCase
from src.infrastructure.llm.catalog.element_llm import (
    get_llm_catalog,
    get_resolve_element_llm,
)


def get_get_llm_catalog_use_case() -> GetLLMCatalogUseCase:
    return GetLLMCatalogUseCase(get_llm_catalog(), get_resolve_element_llm())
