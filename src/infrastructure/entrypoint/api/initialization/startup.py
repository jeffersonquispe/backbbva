from __future__ import annotations

from src.infrastructure.entrypoint.api.initialization.tables import (
    ensure_database_tables,
)


def run_startup_initializers() -> None:
    ensure_database_tables()
