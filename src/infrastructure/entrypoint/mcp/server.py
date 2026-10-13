# No `from __future__ import annotations` here - FastMCP/pydantic build each
# @mcp.tool()'s schema by eval()-ing the function's annotations at import
# time, and that eval loses `typing.Any` out of this module's globals when
# annotations are deferred to strings, raising NameError at import.
import os
from typing import Any
from uuid import UUID

from fastmcp import FastMCP

from src.infrastructure.entrypoint.mcp.bundle import (
    get_loaded_bundle,
    reload_active_model,
)
from src.infrastructure.entrypoint.mcp.factories import get_alert_repository
from src.infrastructure.entrypoint.mcp.scoring import score_row

mcp = FastMCP("aria-xgboost-scoring")


@mcp.tool()
def score_alert(alert_id: str) -> dict[str, Any]:
    """Scores one alert with the currently active XGBoost model. The caller
    (an agent) only ever passes the alert id - never the alert's own field
    values - the tool fetches the canonical alert input itself and builds the
    feature row internally, so no agent prompt has to carry a long
    parameter list of raw alert fields."""
    bundle, model_id, tag = get_loaded_bundle()
    if bundle is None:
        return {"error": "no active model is loaded - call reload_active_model first"}

    alert = get_alert_repository().get(UUID(alert_id))
    if alert is None:
        return {"error": f"alert {alert_id} not found"}

    result = score_row(bundle, alert.input)
    result["model_id"] = model_id
    result["model_tag"] = tag
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
        print(f"reload_active_model failed at startup, starting without a loaded model: {exc}")
    port = int(os.environ.get("MCP_PORT", "8100"))
    mcp.run(transport="streamable-http", host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
