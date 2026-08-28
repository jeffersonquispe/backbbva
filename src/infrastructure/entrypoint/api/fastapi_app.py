from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from src.infrastructure.core.config import genai_config
from src.infrastructure.entrypoint.api.initialization.cors import (
    configure_cors,
)
from src.infrastructure.entrypoint.api.initialization.startup import (
    run_startup_initializers,
)
from src.infrastructure.entrypoint.api.routers.async_operations_router import (
    router as async_operations_router,
)
from src.infrastructure.entrypoint.api.routers.alerts_router import (
    router as alerts_router,
)
from src.infrastructure.entrypoint.api.routers.analyst_capacity_router import (
    router as analyst_capacity_router,
)
from src.infrastructure.entrypoint.api.routers.configurations_router import (
    router as configurations_router,
)
from src.infrastructure.entrypoint.api.routers.datasets_router import (
    router as datasets_router,
)
from src.infrastructure.entrypoint.api.routers.flag_library_router import (
    router as flag_library_router,
)
from src.infrastructure.entrypoint.api.routers.health_router import (
    router as health_router,
)
from src.infrastructure.entrypoint.api.routers.marcacion_catalog_router import (
    router as marcacion_catalog_router,
)
from src.infrastructure.entrypoint.api.routers.modus_operandi_library_router import (
    router as modus_operandi_library_router,
)
from src.infrastructure.entrypoint.api.routers.resolution_method_catalog_router import (
    router as resolution_method_catalog_router,
)
from src.infrastructure.entrypoint.api.routers.similar_case_library_router import (
    router as similar_case_library_router,
)
from src.infrastructure.entrypoint.api.routers.tag_catalog_router import (
    router as tag_catalog_router,
)
from src.infrastructure.entrypoint.api.routers.taxonomy_library_router import (
    router as taxonomy_library_router,
)
from src.infrastructure.entrypoint.api.routers.test_runs_router import (
    router as test_runs_router,
)
from src.infrastructure.entrypoint.api.routers.variable_catalog_router import (
    router as variable_catalog_router,
)
from src.infrastructure.entrypoint.api.routers.watchlists_router import (
    router as watchlists_router,
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    run_startup_initializers()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title=genai_config.COMPONENT_NAME,
        description=genai_config.COMPONENT_DESCRIPTION,
        version=genai_config.COMPONENT_VERSION,
        lifespan=lifespan,
    )
    configure_cors(app)
    app.include_router(health_router)
    app.include_router(
        async_operations_router,
        prefix=genai_config.API_V0_STR,
    )
    app.include_router(
        alerts_router,
        prefix=genai_config.API_V0_STR,
    )
    app.include_router(
        test_runs_router,
        prefix=genai_config.API_V0_STR,
    )
    app.include_router(
        configurations_router,
        prefix=genai_config.API_V0_STR,
    )
    app.include_router(
        datasets_router,
        prefix=genai_config.API_V0_STR,
    )
    app.include_router(
        tag_catalog_router,
        prefix=genai_config.API_V0_STR,
    )
    app.include_router(
        marcacion_catalog_router,
        prefix=genai_config.API_V0_STR,
    )
    app.include_router(
        resolution_method_catalog_router,
        prefix=genai_config.API_V0_STR,
    )
    app.include_router(
        variable_catalog_router,
        prefix=genai_config.API_V0_STR,
    )
    app.include_router(
        taxonomy_library_router,
        prefix=genai_config.API_V0_STR,
    )
    app.include_router(
        modus_operandi_library_router,
        prefix=genai_config.API_V0_STR,
    )
    app.include_router(
        flag_library_router,
        prefix=genai_config.API_V0_STR,
    )
    app.include_router(
        similar_case_library_router,
        prefix=genai_config.API_V0_STR,
    )
    app.include_router(
        analyst_capacity_router,
        prefix=genai_config.API_V0_STR,
    )
    app.include_router(
        watchlists_router,
        prefix=genai_config.API_V0_STR,
    )
    return app


app = create_app()
