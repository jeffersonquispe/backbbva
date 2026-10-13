import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.errors import (
    ConflictError,
    DomainException,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from src.infrastructure.entrypoint.api.fastapi_app import _register_error_handlers


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (ValidationError("invalid"), 422),
        (NotFoundError("missing"), 404),
        (ConflictError("conflict"), 409),
        (ForbiddenError("forbidden"), 403),
        (DomainException("business rule"), 400),
    ],
)
def test_domain_errors_map_to_http_status(error, expected_status):
    app = FastAPI()
    _register_error_handlers(app)

    @app.get("/error")
    def raise_domain_error():
        raise error

    response = TestClient(app).get("/error")
    assert response.status_code == expected_status
    assert response.json() == {"detail": str(error)}
