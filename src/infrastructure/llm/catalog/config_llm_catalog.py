from __future__ import annotations

from src.application.ports.llm_catalog_port import LLMCatalogPort
from src.domain.llm.catalog import LLMCatalog, parse_llm_catalog
from src.infrastructure.core.config import genai_config


class ConfigLLMCatalog(LLMCatalogPort):
    """Catalog read from the ``LLM_CATALOG`` ConfigMap value (no API, no UI)."""

    def __init__(self, raw: str | None = None) -> None:
        self._catalog = parse_llm_catalog(
            genai_config.LLM_CATALOG if raw is None else raw
        )

    def get(self) -> LLMCatalog:
        return self._catalog
