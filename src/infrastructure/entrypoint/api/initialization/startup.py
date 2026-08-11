from __future__ import annotations

from src.infrastructure.entrypoint.api.initialization.opensearch import (
    ensure_fraud_knowledge_index,
)
from src.infrastructure.entrypoint.api.initialization.tables import (
    ensure_database_tables,
)


def run_startup_initializers() -> None:
    ensure_database_tables()
    ensure_fraud_knowledge_index()
