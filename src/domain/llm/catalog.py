"""LLM deployment catalog and the elements that can pick from it.

An *element* is a component of ARIA that calls an LLM. Each one may choose a
catalog entry by its logical ``name``; the deployment behind that name is only
an infrastructure detail (an Azure deployment), so selections store names.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from src.domain import DomainException, ValidationError

# Pipeline steps: resolved per alert run (test overrides apply to these).
WORKFLOW_LLM_ELEMENTS: tuple[str, ...] = (
    "profiling",
    "detector",
    "detector_adversarial",
    "classification",
    "adversarial",
    "analyst",
    "executor",
)
# Every other component that calls an LLM.
SUPPORT_LLM_ELEMENTS: tuple[str, ...] = (
    "report",
    "judge",
    "history_research",
    "assistant_chat",
    "optimizer",
    "agent_drafts",
)
LLM_ELEMENTS: tuple[str, ...] = WORKFLOW_LLM_ELEMENTS + SUPPORT_LLM_ELEMENTS

UNKNOWN_ELEMENT_CODE = "LLM_ELEMENT_UNKNOWN"
UNKNOWN_NAME_CODE = "LLM_CATALOG_NAME_UNKNOWN"
INVALID_CATALOG_CODE = "LLM_CATALOG_INVALID"


class LLMSelectionError(ValidationError):
    """A selection names an element or catalog entry that does not exist."""

    def __init__(self, error_code: str, message: str) -> None:
        self.error_code = error_code
        super().__init__(f"{error_code}: {message}")


class InvalidLLMCatalogError(DomainException, ValueError):
    """The configured catalog is malformed (the process must not start)."""

    error_code = INVALID_CATALOG_CODE


@dataclass(frozen=True)
class LLMCatalogEntry:
    name: str
    deployment: str

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.deployment.strip():
            raise InvalidLLMCatalogError(
                "every catalog entry needs a non-empty name and deployment"
            )


@dataclass(frozen=True)
class LLMCatalog:
    entries: tuple[LLMCatalogEntry, ...] = ()

    def __post_init__(self) -> None:
        names = [entry.name for entry in self.entries]
        if len(set(names)) != len(names):
            raise InvalidLLMCatalogError("catalog names must be unique")

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(entry.name for entry in self.entries)

    def get(self, name: str) -> LLMCatalogEntry | None:
        return next((e for e in self.entries if e.name == name), None)

    def require(self, element: str, name: str) -> LLMCatalogEntry:
        entry = self.get(name)
        if entry is None:
            raise LLMSelectionError(
                UNKNOWN_NAME_CODE,
                f"element '{element}' selects '{name}', which is not in the catalog",
            )
        return entry


def validate_llm_selection(
    selection: Mapping[str, str | None], catalog: LLMCatalog
) -> dict[str, str | None]:
    """Reject unknown elements or names; ``None``/empty means "use the default"."""
    cleaned: dict[str, str | None] = {}
    for element, name in selection.items():
        if element not in LLM_ELEMENTS:
            raise LLMSelectionError(
                UNKNOWN_ELEMENT_CODE, f"'{element}' is not an LLM element"
            )
        if not name:
            cleaned[element] = None
            continue
        catalog.require(element, name)
        cleaned[element] = name
    return cleaned


def parse_llm_catalog(raw: str) -> LLMCatalog:
    """Build the catalog from the ConfigMap value: a JSON list of
    ``{"nombre": ..., "deployment": ...}`` (``name`` is accepted too).
    Empty means "no catalog"; anything malformed raises, so the process
    does not start with a half-understood catalog."""
    import json

    if not raw.strip():
        return LLMCatalog()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InvalidLLMCatalogError(
            f"LLM_CATALOG is not valid JSON: {exc.msg}"
        ) from exc
    if not isinstance(data, list):
        raise InvalidLLMCatalogError("LLM_CATALOG must be a JSON list")
    entries: list[LLMCatalogEntry] = []
    for item in data:
        if not isinstance(item, dict):
            raise InvalidLLMCatalogError("every LLM_CATALOG item must be an object")
        name = item.get("nombre", item.get("name"))
        deployment = item.get("deployment")
        if not isinstance(name, str) or not isinstance(deployment, str):
            raise InvalidLLMCatalogError(
                "every LLM_CATALOG item needs string 'nombre' and 'deployment'"
            )
        entries.append(
            LLMCatalogEntry(name=name.strip(), deployment=deployment.strip())
        )
    return LLMCatalog(entries=tuple(entries))
