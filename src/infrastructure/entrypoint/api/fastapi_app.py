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
from src.infrastructure.entrypoint.api.routers.health_router import (
    router as health_router,
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
    return app


app = create_app()
