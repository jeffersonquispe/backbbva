from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.infrastructure.core.config import genai_config


def configure_cors(app: FastAPI) -> None:
    origins = [
        origin.strip()
        for origin in genai_config.CORS_ALLOWED_ORIGINS.split(",")
        if origin.strip()
    ]
    allow_all = origins == ["*"] or not origins

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if allow_all else origins,
        allow_credentials=not allow_all,
        allow_methods=["*"],
        allow_headers=["*"],
    )
