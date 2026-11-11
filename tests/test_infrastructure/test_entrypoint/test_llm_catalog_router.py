from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.ports.llm_catalog_port import LLMCatalogPort
from src.application.use_cases.llm.get_llm_catalog import GetLLMCatalogUseCase
from src.application.use_cases.llm.resolve_element_llm import ResolveElementLLM
from src.domain.llm.catalog import LLM_ELEMENTS, LLMCatalog, LLMCatalogEntry
from src.infrastructure.entrypoint.api.factories.llm_catalog_factory import (
    get_get_llm_catalog_use_case,
)
from src.infrastructure.entrypoint.api.routers.llm_catalog_router import router


class InMemoryLLMCatalog(LLMCatalogPort):
    def get(self) -> LLMCatalog:
        return LLMCatalog((LLMCatalogEntry("preciso", "gpt-big"),))


def test_llm_catalog_is_listed_with_every_element_and_its_default() -> None:
    app = FastAPI()
    app.include_router(router)
    defaults = {element: f"default-{element}" for element in LLM_ELEMENTS}
    app.dependency_overrides[get_get_llm_catalog_use_case] = (
        lambda: GetLLMCatalogUseCase(
            InMemoryLLMCatalog(), ResolveElementLLM(InMemoryLLMCatalog(), defaults)
        )
    )

    body = TestClient(app).get("/llm-catalog").json()

    assert body["entries"] == [{"name": "preciso", "deployment": "gpt-big"}]
    assert [e["element"] for e in body["elements"]] == list(LLM_ELEMENTS)
    judge = next(e for e in body["elements"] if e["element"] == "judge")
    assert judge == {
        "element": "judge",
        "group": "support",
        "default_deployment": "default-judge",
    }
