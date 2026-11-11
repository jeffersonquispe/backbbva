"""Per-element LLM deployment wiring (catalog, resolver, factory decorators).

Workflow steps resolve their deployment explicitly from the run's own
configuration (see ``workflows/celery/step_context.py``); every other
component asks ``get_element_llm_factory(element)``, whose factory follows the
active configuration's selection on each call. Both paths log failures the
same way: element, logical name, deployment and error code, never provider
text, keys or prompt content.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Mapping
from functools import lru_cache

from src.application.ports.llm_catalog_port import LLMCatalogPort
from src.application.ports.llm_unit_of_work_factory_port import LLMUnitOfWorkFactory
from src.application.ports.llm_unit_of_work_port import (
    LLMInvocationResult,
    LLMMessage,
    LLMUnitOfWork,
)
from src.application.ports.monitoring_port import MonitoringPort
from src.application.use_cases.llm.resolve_element_llm import ResolveElementLLM
from src.infrastructure.core.config import genai_config
from src.infrastructure.llm.catalog.config_llm_catalog import ConfigLLMCatalog
from src.infrastructure.llm.langchain import get_llm_unit_of_work_factory

logger = logging.getLogger(__name__)

_SELECTION_TTL_SECONDS = 30.0


def llm_element_defaults() -> dict[str, str]:
    """element -> deployment used when nothing selects another one."""
    report = genai_config.REPORT_LLM_MODEL
    shared = report or genai_config.EXECUTOR_LLM_MODEL
    return {
        "profiling": genai_config.PROFILING_LLM_MODEL,
        "detector": genai_config.DETECTOR_LLM_MODEL,
        "detector_adversarial": genai_config.DETECTOR_ADVERSARIAL_LLM_MODEL,
        "classification": genai_config.CLASSIFICATION_LLM_MODEL,
        "adversarial": genai_config.ADVERSARIAL_LLM_MODEL,
        "analyst": genai_config.ANALYST_LLM_MODEL,
        "executor": genai_config.EXECUTOR_LLM_MODEL,
        "report": report,
        "judge": genai_config.JUDGE_LLM_MODEL or report,
        "history_research": report,
        "assistant_chat": shared,
        "optimizer": shared,
        "agent_drafts": shared,
    }


@lru_cache(maxsize=1)
def get_llm_catalog() -> LLMCatalogPort:
    return ConfigLLMCatalog()


def get_resolve_element_llm() -> ResolveElementLLM:
    # A fresh use case per call; defaults are read from the live settings.
    return ResolveElementLLM(get_llm_catalog(), llm_element_defaults())


class _ActiveSelection:
    """The active configuration's ``llm_selection``, cached for a few seconds
    so an LLM call does not cost a configuration read."""

    def __init__(self, load: Callable[[], Mapping[str, str | None]]) -> None:
        self._load = load
        self._lock = threading.Lock()
        self._value: Mapping[str, str | None] = {}
        self._loaded_at = float("-inf")

    def get(self) -> Mapping[str, str | None]:
        now = time.monotonic()
        with self._lock:
            if now - self._loaded_at < _SELECTION_TTL_SECONDS:
                return self._value
        try:
            value = self._load()
        except Exception:  # noqa: BLE001 - selection is optional; keep serving defaults
            logger.warning("Could not read the active LLM selection; using defaults")
            value = {}
        with self._lock:
            self._value, self._loaded_at = value, now
        return value


def _load_active_selection() -> Mapping[str, str | None]:
    from src.infrastructure.persistence.database.dynamodb.repositories.configuration_repository import (
        DynamoConfigurationRepository,
    )

    active = DynamoConfigurationRepository().get_active()
    return dict(active.general.llm_selection) if active is not None else {}


@lru_cache(maxsize=1)
def get_active_llm_selection() -> _ActiveSelection:
    return _ActiveSelection(_load_active_selection)


class _LoggingLLMUnitOfWork(LLMUnitOfWork):
    def __init__(
        self, inner: LLMUnitOfWork, element: str, name: str | None, deployment: str
    ) -> None:
        self._inner = inner
        self._element = element
        self._name = name
        self._deployment = deployment

    def invoke(self, messages: list[LLMMessage]) -> LLMInvocationResult:
        try:
            return self._inner.invoke(messages)
        except Exception as exc:
            # Only the exception class: provider text can echo prompts or keys.
            logger.error(
                "LLM call failed element=%s name=%s deployment=%s error_code=%s",
                self._element,
                self._name,
                self._deployment,
                type(exc).__name__,
            )
            raise


class ElementLLMUnitOfWorkFactory(LLMUnitOfWorkFactory):
    """Factory for one element: failure logging, and optionally the active
    configuration's selection applied on every ``create``."""

    def __init__(
        self,
        inner: LLMUnitOfWorkFactory,
        element: str,
        catalog: LLMCatalogPort,
        resolver: ResolveElementLLM,
        selection: _ActiveSelection | None,
    ) -> None:
        self._inner = inner
        self._element = element
        self._catalog = catalog
        self._resolver = resolver
        self._selection = selection

    def create(
        self,
        *,
        model: str,
        monitoring: MonitoringPort,
        operation_name: str,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> LLMUnitOfWork:
        deployment, name = model, None
        if self._selection is not None:
            resolved = self._resolver.execute(
                self._element, selection=self._selection.get()
            )
            if resolved.name is not None:
                deployment, name = resolved.deployment, resolved.name
        if name is None:
            name = next(
                (
                    e.name
                    for e in self._catalog.get().entries
                    if e.deployment == deployment
                ),
                None,
            )
        unit = self._inner.create(
            model=deployment,
            monitoring=monitoring,
            operation_name=operation_name,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return _LoggingLLMUnitOfWork(unit, self._element, name, deployment)


def get_element_llm_factory(
    element: str, follow_selection: bool = True
) -> LLMUnitOfWorkFactory:
    """LLM factory for ``element``. ``follow_selection=False`` is for callers
    that already resolved the deployment from their own configuration."""
    get_resolve_element_llm().default_for(element)  # rejects unknown elements
    return ElementLLMUnitOfWorkFactory(
        get_llm_unit_of_work_factory(),
        element,
        get_llm_catalog(),
        get_resolve_element_llm(),
        get_active_llm_selection() if follow_selection else None,
    )


def effective_model(element: str) -> str:
    """The deployment ``element`` runs with right now (active selection or
    default). Used by wiring that needs the string up front."""
    return (
        get_resolve_element_llm()
        .execute(element, selection=get_active_llm_selection().get())
        .deployment
    )
