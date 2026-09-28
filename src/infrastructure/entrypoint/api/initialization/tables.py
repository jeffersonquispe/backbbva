from __future__ import annotations

import logging

from src.infrastructure.core.config import genai_config
from src.infrastructure.persistence.database.dynamodb.manager import (
    ensure_all_tables,
    seed_defaults,
)
from src.infrastructure.persistence.database.dynamodb.simulator_schemas import (
    ensure_simulator_tables,
)

log = logging.getLogger(__name__)


def ensure_database_tables() -> None:
    if not genai_config.DYNAMO_ENDPOINT:
        return

    try:
        ensure_all_tables()
        seed_defaults()
        # Deliberately separate from ensure_all_tables()/manager.py - see
        # simulator_schemas.py's docstring on why it stays a light,
        # independent schema module shared with simulator-worker.
        ensure_simulator_tables()
    except Exception:
        log.exception("DynamoDB table initialization failed")
        raise
