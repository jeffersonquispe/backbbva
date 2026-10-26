from __future__ import annotations

from fastapi import FastAPI

from src.infrastructure.entrypoint.api.routers.async_operations_router import (
    router,
)


def test_generic_create_and_manual_reconcile_routes_are_not_exposed() -> None:
    app = FastAPI()
    app.include_router(router)
    routes = {
        (method, route.path)
        for route in app.routes
        if hasattr(route, "methods")
        for method in route.methods or set()
    }

    assert ("GET", "/async-operations") in routes
    assert ("GET", "/async-operations/{operation_id}") in routes
    assert ("GET", "/async-operations/{operation_id}/poll") in routes
    assert ("PATCH", "/async-operations/{operation_id}") in routes
    assert ("POST", "/async-operations") not in routes
    assert ("POST", "/async-operations/reconcile") not in routes
