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
_bundle_cache_lock = threading.Lock()
_bundle_cache: dict[str, Any] = {}
_state: dict[str, Any] = {"storage_ref": None, "model_id": None, "tag": None}


def get_model_bundle(storage_ref: str) -> dict[str, Any]:
    with _bundle_cache_lock:
        if storage_ref not in _bundle_cache:
            bundle = joblib.load(BytesIO(get_model_storage().get_bytes(storage_ref)))
            _bundle_cache.clear()
            _bundle_cache[storage_ref] = bundle
        return _bundle_cache[storage_ref]


def reload_active_model() -> dict[str, Any]:
    """Reloads the in-memory scoring bundle from whatever model is currently
    ModelRepository.active - the "recarga forzada a la version sugerida por
    la configuracion activa" tool. Called once at server startup and again
    on demand (e.g. right after an admin activates a different model
    version in the UI)."""
    model_repository = get_model_repository()
    model = model_repository.get_active()
    if model is None or model.storage_ref is None:
        with _bundle_cache_lock:
            _bundle_cache.clear()
        with _lock:
            _state["storage_ref"] = None
            _state["model_id"] = None
            _state["tag"] = None
        return {"loaded": False, "reason": "no active, trained model"}

    bundle = get_model_bundle(model.storage_ref)
    with _lock:
        _state["storage_ref"] = model.storage_ref
        _state["model_id"] = str(model.id)
        _state["tag"] = model.tag
    return {
        "loaded": True,
        "model_id": str(model.id),
        "tag": model.tag,
        "columns": bundle["columns"],
        "metrics": bundle.get("metrics"),
    }


def get_loaded_model() -> tuple[str | None, str | None, str | None]:
    with _lock:
        return _state["storage_ref"], _state["model_id"], _state["tag"]
