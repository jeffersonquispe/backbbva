from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.application.errors import (
    ConflictError,
    DomainException,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from src.infrastructure.core.config import genai_config
from src.infrastructure.entrypoint.api.audit_middleware import AuditContextMiddleware
from src.infrastructure.entrypoint.api.initialization.cors import (
    configure_cors,
)
from src.infrastructure.entrypoint.api.initialization.startup import (
    run_startup_initializers,
)
from src.infrastructure.entrypoint.api.routers.agent_draft_actions_router import (
    router as agent_draft_actions_router,
)
from src.infrastructure.entrypoint.api.routers.agent_flag_draft_router import (
    router as agent_flag_draft_router,
)
from src.infrastructure.entrypoint.api.routers.agent_modus_operandi_draft_router import (
    router as agent_modus_operandi_draft_router,
)
from src.infrastructure.entrypoint.api.routers.agent_objectives_router import (
    router as agent_objectives_router,
)
from src.infrastructure.entrypoint.api.routers.agent_release_router import (
    router as agent_release_router,
)
from src.infrastructure.entrypoint.api.routers.agent_router import (
    router as agent_router,
)
from src.infrastructure.entrypoint.api.routers.agent_similar_case_draft_router import (
    router as agent_similar_case_draft_router,
)
from src.infrastructure.entrypoint.api.routers.agent_taxonomy_draft_router import (
    router as agent_taxonomy_draft_router,
)
from src.infrastructure.entrypoint.api.routers.agent_watchlist_draft_router import (
    router as agent_watchlist_draft_router,
)
from src.infrastructure.entrypoint.api.routers.alert_schema_router import (
    router as alert_schema_router,
)
from src.infrastructure.entrypoint.api.routers.alerts_router import (
    router as alerts_router,
)
from src.infrastructure.entrypoint.api.routers.analyst_capacity_router import (
    router as analyst_capacity_router,
)
from src.infrastructure.entrypoint.api.routers.analyst_queue_router import (
    router as analyst_queue_router,
)
from src.infrastructure.entrypoint.api.routers.assistant_optimizer_settings_router import (
    router as assistant_optimizer_settings_router,
)
from src.infrastructure.entrypoint.api.routers.async_operations_router import (
    router as async_operations_router,
)
from src.infrastructure.entrypoint.api.routers.auth_router import (
    router as auth_router,
)
from src.infrastructure.entrypoint.api.routers.backups_router import (
    router as backups_router,
)
from src.infrastructure.entrypoint.api.routers.channel_library_router import (
    router as channel_library_router,
)
from src.infrastructure.entrypoint.api.routers.configuration_deploy_requests_router import (
    router as configuration_deploy_requests_router,
)
from src.infrastructure.entrypoint.api.routers.configurations_router import (
    configuration_test_router,
)
from src.infrastructure.entrypoint.api.routers.configurations_router import (
    router as configurations_router,
)
from src.infrastructure.entrypoint.api.routers.datasets_router import (
    router as datasets_router,
)
from src.infrastructure.entrypoint.api.routers.e2e_router import (
    router as e2e_router,
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
from src.infrastructure.entrypoint.api.routers.metrics_router import (
    router as metrics_router,
)
from src.infrastructure.entrypoint.api.routers.models_router import (
    router as models_router,
)
from src.infrastructure.entrypoint.api.routers.modus_operandi_library_router import (
    router as modus_operandi_library_router,
)
from src.infrastructure.entrypoint.api.routers.operational_settings_router import (
    router as operational_settings_router,
)
from src.infrastructure.entrypoint.api.routers.operations_router import (
    router as operations_router,
)
from src.infrastructure.entrypoint.api.routers.resolution_method_catalog_router import (
    router as resolution_method_catalog_router,
)
from src.infrastructure.entrypoint.api.routers.scenarios_router import (
    router as scenarios_router,
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
from src.infrastructure.entrypoint.api.routers.vector_store_instances_router import (
    router as vector_store_instances_router,
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
    _register_error_handlers(app)
    app.add_middleware(AuditContextMiddleware)
    configure_cors(app)
    app.include_router(health_router)
    app.include_router(auth_router, prefix=genai_config.API_V0_STR)
    app.include_router(agent_router, prefix=genai_config.API_V0_STR)
    app.include_router(agent_draft_actions_router, prefix=genai_config.API_V0_STR)
    app.include_router(agent_modus_operandi_draft_router, prefix=genai_config.API_V0_STR)
    app.include_router(agent_taxonomy_draft_router, prefix=genai_config.API_V0_STR)
    app.include_router(agent_similar_case_draft_router, prefix=genai_config.API_V0_STR)
    app.include_router(agent_watchlist_draft_router, prefix=genai_config.API_V0_STR)
    app.include_router(agent_flag_draft_router, prefix=genai_config.API_V0_STR)
    app.include_router(agent_objectives_router, prefix=genai_config.API_V0_STR)
    app.include_router(agent_release_router, prefix=genai_config.API_V0_STR)
    app.include_router(backups_router, prefix=genai_config.API_V0_STR)
    app.include_router(alert_schema_router, prefix=genai_config.API_V0_STR)
    app.include_router(e2e_router, prefix=genai_config.API_V0_STR)
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
        configuration_test_router,
        prefix=genai_config.API_V0_STR,
    )
    app.include_router(
        configuration_deploy_requests_router,
        prefix=genai_config.API_V0_STR,
    )
    app.include_router(
        operational_settings_router,
        prefix=genai_config.API_V0_STR,
    )
    app.include_router(
        assistant_optimizer_settings_router,
        prefix=genai_config.API_V0_STR,
    )
    app.include_router(
        analyst_queue_router,
        prefix=genai_config.API_V0_STR,
    )
    app.include_router(
        operations_router,
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
        channel_library_router,
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
        vector_store_instances_router,
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
    app.include_router(
        models_router,
        prefix=genai_config.API_V0_STR,
    )
    app.include_router(
        scenarios_router,
        prefix=genai_config.API_V0_STR,
    )
    app.include_router(
        metrics_router,
        prefix=genai_config.API_V0_STR,
    )
    return app


def _register_error_handlers(app: FastAPI) -> None:
    """Translate business errors to stable HTTP responses in one place."""

    @app.exception_handler(ValidationError)
    async def validation_error_handler(
        request: Request, exc: ValidationError
    ) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(NotFoundError)
    async def not_found_error_handler(
        request: Request, exc: NotFoundError
    ) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(ConflictError)
    async def conflict_error_handler(
        request: Request, exc: ConflictError
    ) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(ForbiddenError)
    async def forbidden_error_handler(
        request: Request, exc: ForbiddenError
    ) -> JSONResponse:
        return JSONResponse(status_code=403, content={"detail": str(exc)})

    @app.exception_handler(DomainException)
    async def domain_error_handler(
        request: Request, exc: DomainException
    ) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})


app = create_app()
