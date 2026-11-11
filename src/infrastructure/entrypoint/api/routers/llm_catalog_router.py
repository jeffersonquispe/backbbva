from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from src.application.use_cases.llm.get_llm_catalog import GetLLMCatalogUseCase
from src.infrastructure.entrypoint.api.factories.llm_catalog_factory import (
    get_get_llm_catalog_use_case,
)
from src.infrastructure.entrypoint.api.schemas.llm_catalog import (
    LLMCatalogEntrySchema,
    LLMCatalogResponse,
    LLMElementSchema,
)

router = APIRouter(prefix="/llm-catalog", tags=["llm-catalog"])


@router.get("", response_model=LLMCatalogResponse)
def get_llm_catalog(
    use_case: Annotated[GetLLMCatalogUseCase, Depends(get_get_llm_catalog_use_case)],
):
    """Read-only: the catalog comes from the ConfigMap (``LLM_CATALOG``)."""
    output = use_case.execute()
    return LLMCatalogResponse(
        entries=[
            LLMCatalogEntrySchema(name=e.name, deployment=e.deployment)
            for e in output.entries
        ],
        elements=[
            LLMElementSchema(
                element=e.element,
                group=e.group,
                default_deployment=e.default_deployment,
            )
            for e in output.elements
        ],
    )
