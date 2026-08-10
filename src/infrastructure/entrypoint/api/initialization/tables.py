from __future__ import annotations

import logging

from src.infrastructure.core.config import genai_config
from src.infrastructure.persistence.database.dynamodb.manager import (
    ensure_all_tables,
    seed_defaults,
)

log = logging.getLogger(__name__)


def ensure_database_tables() -> None:
    if not genai_config.DYNAMO_ENDPOINT:
        return

    try:
        ensure_all_tables()
        seed_defaults()
    except Exception:
        log.exception("DynamoDB table initialization failed")
        raise
