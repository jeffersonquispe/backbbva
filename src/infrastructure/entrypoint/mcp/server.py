# No `from __future__ import annotations` here - FastMCP/pydantic build each
# @mcp.tool()'s schema by eval()-ing the function's annotations at import
# time, and that eval loses `typing.Any` out of this module's globals when
# annotations are deferred to strings, raising NameError at import.
from hashlib import sha256
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
    get_model_storage,
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


@mcp.custom_route("/internal/score-pinned-row", methods=["POST"])
async def score_pinned_row_http(request: Request) -> JSONResponse:
    try:
        body = await request.json()
        model_id = str(UUID(body["model_id"]))
        digest = body["artifact_sha256"]
        row = body["row"]
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
            or not isinstance(row, dict)
            or not row
        ):
            raise ValueError("invalid pinned model row")
    except (KeyError, TypeError, ValueError):
        return JSONResponse({"error": "PINNED_MODEL_INPUT_INVALID"}, status_code=422)
    result = await run_in_threadpool(_score_pinned_model_row, model_id, digest, row)
    return JSONResponse(result, status_code=422 if "error" in result else 200)


def _score_pinned_model_row(
    model_id: str, artifact_sha256: str, row: dict[str, Any]
) -> dict[str, Any]:
    model = get_model_repository().get(UUID(model_id))
    if model is None:
        return {"error": "PINNED_MODEL_UNAVAILABLE"}
    storage_ref = f"models/sha256/{artifact_sha256}.joblib"
    try:
        artifact = get_model_storage().get_bytes(storage_ref)
    except (KeyError, OSError):
        return {"error": "PINNED_MODEL_ARTIFACT_UNAVAILABLE"}
    if sha256(artifact).hexdigest() != artifact_sha256:
        return {"error": "PINNED_MODEL_ARTIFACT_MISMATCH"}
    result = score_row(get_model_bundle(storage_ref), row)
    result["model_id"] = model_id
    result["model_tag"] = model.tag
    result["artifact_sha256"] = artifact_sha256
    return result


@mcp.custom_route("/internal/score-pinned-pipeline", methods=["POST"])
async def score_pinned_pipeline_http(request: Request) -> JSONResponse:
    try:
        body = await request.json()
        if (
            body.get("knowledge_decision_policy") != "evidence_only_v1"
            or not isinstance(body.get("rows"), list)
            or not body["rows"]
            or not isinstance(body.get("configuration"), dict)
            or not isinstance(body.get("library"), dict)
            or not isinstance(body.get("vector_store"), dict)
        ):
            raise ValueError("invalid pinned pipeline")
        model_id = str(UUID(body["model_id"]))
        artifact_sha256 = body["artifact_sha256"]
        if (
            not isinstance(artifact_sha256, str)
            or len(artifact_sha256) != 64
            or any(char not in "0123456789abcdef" for char in artifact_sha256)
        ):
            raise ValueError("invalid model digest")
    except (KeyError, TypeError, ValueError):
        return JSONResponse({"error": "PINNED_PIPELINE_INPUT_INVALID"}, status_code=422)
    result = await run_in_threadpool(
        _score_pinned_pipeline,
        model_id,
        artifact_sha256,
        body["configuration"],
        body["library"],
        body["vector_store"],
        body["rows"],
    )
    if "error" in result:
        return JSONResponse(result, status_code=422)
    return JSONResponse(result)


def _score_pinned_pipeline(
    model_id: str,
    artifact_sha256: str,
    configuration: dict[str, Any],
    library: dict[str, Any],
    vector_store: dict[str, Any],
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    try:
        model = get_model_repository().get(UUID(model_id))
        if model is None:
            return {"error": "PINNED_MODEL_UNAVAILABLE"}
        storage_ref = f"models/sha256/{artifact_sha256}.joblib"
        artifact = get_model_storage().get_bytes(storage_ref)
        if sha256(artifact).hexdigest() != artifact_sha256:
            return {"error": "PINNED_MODEL_ARTIFACT_MISMATCH"}
        bundle = get_model_bundle(storage_ref)
        segments = configuration.get("segments")
        if not isinstance(segments, dict) or not segments:
            return {"error": "PINNED_CONFIGURATION_SEGMENTS_MISSING"}
        enabled = [
            (name, value)
            for name, value in segments.items()
            if isinstance(value, dict) and value.get("enabled")
        ]
        predictions = []
        if not enabled:
            # With no active segment override, the pinned configuration has no
            # threshold rule; use the threshold embedded in the pinned model
            # bundle as the configured default for this exact model revision.
            threshold = bundle.get("threshold", 0.5)
            if not isinstance(threshold, (int, float)) or not 0 <= threshold <= 1:
                return {"error": "PINNED_MODEL_THRESHOLD_INVALID"}
            for row in rows:
                scored = score_row(bundle, row)
                predictions.append(float(scored["score"]) >= float(threshold))
            return {
                "predicted_positive": predictions,
                "knowledge_evidence_assets": _knowledge_evidence_count(
                    vector_store, library
                ),
                "knowledge_decision_policy": "evidence_only_v1",
            }
        for row in rows:
            selected = next(
                (
                    (name, value)
                    for name, value in sorted(
                        enabled, key=lambda item: int(item[1].get("order", 0))
                    )
                    if _segment_filter_matches(value.get("filter", {}), row)
                ),
                None,
            )
            if selected is None:
                return {"error": "PINNED_CONFIGURATION_SEGMENT_UNRESOLVED"}
            detector = selected[1].get("agent", {}).get("detector", {})
            threshold_value = detector.get("xgboost_fraud_threshold")
            if not isinstance(threshold_value, (int, float)):
                return {"error": "PINNED_CONFIGURATION_THRESHOLD_MISSING"}
            threshold = float(threshold_value)
            if threshold < 0 or threshold > 1:
                return {"error": "PINNED_CONFIGURATION_THRESHOLD_INVALID"}
            scored = score_row(bundle, row)
            predictions.append(float(scored["score"]) >= threshold)
        return {
            "predicted_positive": predictions,
            "knowledge_evidence_assets": _knowledge_evidence_count(
                vector_store, library
            ),
            "knowledge_decision_policy": "evidence_only_v1",
        }
    except (KeyError, TypeError, ValueError, OSError):
        return {"error": "PINNED_PIPELINE_SCORING_FAILED"}


def _knowledge_evidence_count(
    vector_store: dict[str, Any], library: dict[str, Any]
) -> int:
    assets = vector_store.get("assets", [])
    library_id = library.get("id")
    return sum(
        1
        for asset in assets
        if isinstance(asset, dict) and asset.get("asset_id") == library_id
    )


def _segment_filter_matches(group: dict[str, Any], row: dict[str, Any]) -> bool:
    if not isinstance(group, dict):
        return False
    values: dict[str, set[str]] = {}
    for field, category in (
        ("event_type", "event_type"),
        ("integration_point", "integration_point"),
    ):
        if row.get(field) not in (None, ""):
            values[category] = {str(row[field])}
    rules = row.get("rules")
    if isinstance(rules, list):
        values["triggered_rule"] = {
            str(item.get("name")) if isinstance(item, dict) else str(item)
            for item in rules
            if item not in (None, "")
        }
    elif isinstance(rules, str):
        values["triggered_rule"] = {
            token.strip() for token in rules.strip("[]").split(",") if token.strip()
        }
    conditions = group.get("conditions", [])
    nested = group.get("groups", [])
    matches = []
    if isinstance(conditions, list):
        for condition in conditions:
            if not isinstance(condition, dict):
                return False
            category = str(condition.get("category", ""))
            accepted = condition.get("values", [])
            if not isinstance(accepted, list):
                return False
            matches.append(
                bool(values.get(category, set()) & {str(v) for v in accepted})
            )
    if isinstance(nested, list):
        matches.extend(_segment_filter_matches(item, row) for item in nested)
    elif nested:
        return False
    if not matches:
        return True
    if str(group.get("operator", "and")).lower().endswith("or"):
        return any(matches)
    return all(matches)


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
