# No `from __future__ import annotations` here - FastMCP/pydantic build each
# @mcp.tool()'s schema by eval()-ing the function's annotations at import
# time, and that eval loses `typing.Any` out of this module's globals when
# annotations are deferred to strings, raising NameError at import.
from typing import Any
from uuid import UUID

from fastmcp import FastMCP
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse

from src.infrastructure.core.config import genai_config
from src.infrastructure.entrypoint.mcp.bundle import (
    get_loaded_model,
    get_model_bundle,
    reload_active_model,
)
from src.infrastructure.entrypoint.mcp.factories import (
    get_alert_repository,
    get_model_repository,
)
from src.infrastructure.entrypoint.mcp.scoring import score_row

mcp = FastMCP("aria-xgboost-scoring")


def _score_alert(alert_id: str, model_id: str | None = None) -> dict[str, Any]:
    loaded_storage_ref, loaded_model_id, loaded_tag = get_loaded_model()
    if model_id is None:
        if loaded_storage_ref is None or loaded_model_id is None:
            return {"error": "no active model is loaded"}
        model_id = loaded_model_id
        model_tag = loaded_tag or "unknown"
        storage_ref = loaded_storage_ref
    else:
        model = get_model_repository().get(UUID(model_id))
        if model is None or model.storage_ref is None:
            return {"error": "requested model is not trained or does not exist"}
        model_id = str(model.id)
        model_tag = model.tag
        storage_ref = model.storage_ref
    bundle = get_model_bundle(storage_ref)
    alert = get_alert_repository().get(UUID(alert_id))
    if alert is None:
        return {"error": f"alert {alert_id} not found"}
    result = score_row(bundle, alert.input)
    result["model_id"] = model_id
    result["model_tag"] = model_tag
    return result


@mcp.tool()
def score_alert(alert_id: str, model_id: str | None = None) -> dict[str, Any]:
    """Scores one alert with the currently active XGBoost model. The caller
    (an agent) only ever passes the alert id - never the alert's own field
    values - the tool fetches the canonical alert input itself and builds the
    feature row internally, so no agent prompt has to carry a long
    parameter list of raw alert fields."""
    return _score_alert(alert_id, model_id)


@mcp.custom_route("/internal/score", methods=["POST"])
async def score_alert_http(request: Request) -> JSONResponse:
    try:
        body = await request.json()
        alert_id = str(UUID(body["alert_id"]))
        model_id = str(UUID(body["model_id"])) if body.get("model_id") else None
    except (KeyError, TypeError, ValueError):
        return JSONResponse(
            {"error": "alert_id and optional model_id must be UUIDs"},
            status_code=422,
        )
    result = await run_in_threadpool(_score_alert, alert_id, model_id)
    return JSONResponse(result, status_code=404 if "error" in result else 200)


@mcp.custom_route("/internal/score-row", methods=["POST"])
async def score_row_http(request: Request) -> JSONResponse:
    try:
        body = await request.json()
        model_id = str(UUID(body["model_id"]))
        row = body["row"]
        if not isinstance(row, dict) or not row:
            raise ValueError("row must be a non-empty object")
    except (KeyError, TypeError, ValueError):
        return JSONResponse(
            {"error": "model_id must be a UUID and row must be a non-empty object"},
            status_code=422,
        )
    result = await run_in_threadpool(_score_model_row, model_id, row)
    return JSONResponse(result, status_code=404 if "error" in result else 200)


@mcp.custom_route("/internal/reload-active-model", methods=["POST"])
async def reload_active_model_http(request: Request) -> JSONResponse:
    try:
        result = await run_in_threadpool(reload_active_model)
    except Exception as exc:  # noqa: BLE001 - report the serving transition to the API
        return JSONResponse({"error": str(exc)}, status_code=503)
    return JSONResponse(result, status_code=200 if result.get("loaded") else 409)


def _score_model_row(model_id: str, row: dict[str, Any]) -> dict[str, Any]:
    model = get_model_repository().get(UUID(model_id))
    if model is None or model.storage_ref is None:
        return {"error": "requested model is not trained or does not exist"}
    result = score_row(get_model_bundle(model.storage_ref), row)
    result["model_id"] = str(model.id)
    result["model_tag"] = model.tag
    return result


@mcp.tool()
def reload_model() -> dict[str, Any]:
    """Forces the in-memory model bundle to reload from whatever version is
    currently active in ModelRepository (the model picked in the
    configuracion/agente UI's model selector). Not meant for the scoring
    agent's own tool list - an internal/ops tool to pick up a newly
    activated model version without restarting this service."""
    return reload_active_model()


def main() -> None:
    # No active/trained model yet is a normal first-boot state (nothing to
    # score until an admin trains and activates one from /modelos) - the
    # server must still come up and serve reload_model for later, not crash
    # the whole container over it.
    try:
        reload_active_model()
    except Exception as exc:  # noqa: BLE001
        print(
            f"reload_active_model failed at startup, starting without a loaded model: {exc}"
        )
    mcp.run(transport="streamable-http", host="0.0.0.0", port=genai_config.MCP_PORT)


if __name__ == "__main__":
    main()
