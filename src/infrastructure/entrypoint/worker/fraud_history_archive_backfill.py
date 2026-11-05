"""Index the cold fraud-history archive by alert_id (#11c):

    make fraud-history-archive-index-backfill DRY_RUN=0

Archive objects written before the index existed (or after an index loss) are
read once and every alert in them is indexed, so the API can serve
``GET /fraud-history/archive/{alert_id}`` for them. Idempotent: alerts that
already have an index entry are left alone. Dry run unless ``--apply``.

Runs where the worker runs (worker factories): on the host against the local
stack (the Make target), or inside a worker pod in OKD."""

from __future__ import annotations

import argparse
import json
import logging

from src.infrastructure.persistence.database.dynamodb.manager import create_table
from src.infrastructure.persistence.database.dynamodb.schemas import (
    FRAUD_HISTORY_ARCHIVE_INDEX_TABLE,
    LEGAL_HOLDS_TABLE,
)
from src.infrastructure.workflows.celery.task_factories import (
    get_fraud_history_archive_reader,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--apply", action="store_true", help="write the index (default: dry run)"
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)

    create_table(FRAUD_HISTORY_ARCHIVE_INDEX_TABLE)
    create_table(LEGAL_HOLDS_TABLE)
    result = get_fraud_history_archive_reader().backfill_index(dry_run=not args.apply)
    print(
        json.dumps(
            {
                "dry_run": not args.apply,
                "objects": result.objects,
                "alerts": result.alerts,
                "indexed": result.indexed,
                "already_indexed": result.already_indexed,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
