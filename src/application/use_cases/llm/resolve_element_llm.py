from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from src.application.ports.llm_catalog_port import LLMCatalogPort
from src.domain.llm.catalog import LLM_ELEMENTS, UNKNOWN_ELEMENT_CODE, LLMSelectionError

SOURCE_OVERRIDE = "override"
SOURCE_CONFIGURATION = "configuration"
SOURCE_DEFAULT = "default"


@dataclass(frozen=True)
class ResolvedLLM:
    element: str
    deployment: str
    # Logical catalog name; None when the element runs on its default.
    name: str | None
    source: str

    def as_dict(self) -> dict[str, str | None]:
        return {
            "element": self.element,
            "name": self.name,
            "deployment": self.deployment,
            "source": self.source,
        }


class ResolveElementLLM:
    """Which deployment an element runs with.

    Priority: the test run's override -> the configuration's selection ->
    the element's default (its ``*_LLM_MODEL`` setting). A name outside the
    catalog fails with a clear error code: there is no silent fallback.
    """

    def __init__(self, catalog: LLMCatalogPort, defaults: Mapping[str, str]) -> None:
        self._catalog = catalog
        self._defaults = defaults

    def default_for(self, element: str) -> str:
        self._check_element(element)
        return self._defaults.get(element, "")

    def execute(
        self,
        element: str,
        *,
        override: str | None = None,
        selection: Mapping[str, str | None] | None = None,
    ) -> ResolvedLLM:
        self._check_element(element)
        catalog = self._catalog.get()
        if override:
            if catalog.entries:
                return ResolvedLLM(
                    element,
                    catalog.require(element, override).deployment,
                    override,
                    SOURCE_OVERRIDE,
                )
            # No catalog configured: legacy runs carry a raw deployment name.
            return ResolvedLLM(element, override, None, SOURCE_OVERRIDE)
        chosen = (selection or {}).get(element)
        if chosen:
            return ResolvedLLM(
                element,
                catalog.require(element, chosen).deployment,
                chosen,
                SOURCE_CONFIGURATION,
            )
        return ResolvedLLM(
            element, self._defaults.get(element, ""), None, SOURCE_DEFAULT
        )

    @staticmethod
    def _check_element(element: str) -> None:
        if element not in LLM_ELEMENTS:
            raise LLMSelectionError(
                UNKNOWN_ELEMENT_CODE, f"'{element}' is not an LLM element"
            )
