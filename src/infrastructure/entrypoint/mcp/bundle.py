from __future__ import annotations

import threading
from io import BytesIO
from typing import Any

import joblib

from src.infrastructure.entrypoint.mcp.factories import (
    get_model_repository,
    get_model_storage,
)

_lock = threading.Lock()
_state: dict[str, Any] = {"bundle": None, "model_id": None, "tag": None}


def reload_active_model() -> dict[str, Any]:
    """Reloads the in-memory scoring bundle from whatever model is currently
    ModelRepository.active - the "recarga forzada a la version sugerida por
    la configuracion activa" tool. Called once at server startup and again
    on demand (e.g. right after an admin activates a different model
    version in the UI)."""
    model_repository = get_model_repository()
    model = model_repository.get_active()
    if model is None or model.storage_ref is None:
        with _lock:
            _state["bundle"] = None
            _state["model_id"] = None
            _state["tag"] = None
        return {"loaded": False, "reason": "no active, trained model"}

    content = get_model_storage().get_bytes(model.storage_ref)
    bundle = joblib.load(BytesIO(content))
    with _lock:
        _state["bundle"] = bundle
        _state["model_id"] = str(model.id)
        _state["tag"] = model.tag
    return {
        "loaded": True,
        "model_id": str(model.id),
        "tag": model.tag,
        "columns": bundle["columns"],
        "metrics": bundle.get("metrics"),
    }


def get_loaded_bundle() -> tuple[dict[str, Any] | None, str | None, str | None]:
    with _lock:
        return _state["bundle"], _state["model_id"], _state["tag"]
