from __future__ import annotations

from fastapi import APIRouter

from src.infrastructure.core.config import genai_config

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "component": genai_config.COMPONENT_NAME,
        "version": genai_config.COMPONENT_VERSION,
    }
