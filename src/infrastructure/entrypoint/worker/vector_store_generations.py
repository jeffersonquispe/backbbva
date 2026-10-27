"""Vector-store generation maintenance:

    make vector-store-generations-migrate [DRY_RUN=0]
    make vector-store-generations-cleanup [DRY_RUN=0]
    python -m src.infrastructure.entrypoint.worker.vector_store_generations migrate --apply

``migrate`` turns each instance's legacy promoted generation into a
generation record and pins every saved configuration tool to it (see
vector_store_generation_migration.py). ``cleanup`` runs the nightly
retention (vector_store.cleanup_generations) once. Both are dry runs unless
``--apply`` is given.

Runs where the worker runs (it uses the worker factories): on the host
against the local stack (the Make targets), or inside a worker pod in OKD."""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import asdict

from src.infrastructure.core.config import genai_config
from src.infrastructure.persistence.database.dynamodb.vector_store_generation_migration import (
    VectorStoreGenerationMigration,
)
from src.infrastructure.persistence.vector_store.opensearch.client import (
    get_opensearch_client,
)
from src.infrastructure.workflows.celery.factories import (
    get_vector_store_generation_repository,
    get_vector_store_instance_repository,
)
from src.infrastructure.workflows.celery.task_factories import (
    get_cleanup_vector_store_generations_use_case,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=["migrate", "cleanup"])
    parser.add_argument(
        "--apply", action="store_true", help="write changes (default: dry run)"
    )
    parser.add_argument(
        "--instance", help="cleanup: only this vector-store instance's generations"
    )
    parser.add_argument(
        "--retention-days",
        type=int,
        default=genai_config.VECTOR_STORE_GENERATION_RETENTION_DAYS,
        help="cleanup: retire unprotected READY generations older than this "
        "(0 = every unprotected one)",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    dry_run = not args.apply

    if args.command == "migrate":
        report = VectorStoreGenerationMigration(
            instances=get_vector_store_instance_repository(),
            generations=get_vector_store_generation_repository(),
            opensearch=get_opensearch_client(),
        ).run(dry_run=dry_run)
        print(json.dumps(asdict(report), indent=2, ensure_ascii=False))
        return 1 if report.segment_tools_unresolved else 0

    if args.retention_days < 0:
        parser.error("--retention-days must be 0 or more")
    output = get_cleanup_vector_store_generations_use_case().execute(
        retention_days=args.retention_days,
        rollback_configurations=genai_config.VECTOR_STORE_ROLLBACK_CONFIGURATIONS,
        dry_run=dry_run,
        instance_id=args.instance,
    )
    print(json.dumps(asdict(output), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
