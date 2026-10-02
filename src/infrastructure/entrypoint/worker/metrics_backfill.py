"""Metrics backfill command (R6):

    make metrics-backfill FROM=YYYY-MM-DD TO=YYYY-MM-DD
    python -m src.infrastructure.entrypoint.worker.metrics_backfill --from ... --to ...

Days are operations-timezone (Bogota) calendar days, inclusive. Steps:
1. make sure the alerts table has its indexes (idempotent);
2. one bounded pass over the alerts partition that sets created_day on the
   alerts of the range written before that attribute existed, so the
   CreatedDayIdx index can serve them;
3. BackfillAlertMetrics: alerts without a metrics snapshot get it (and
   their rollup contribution) rebuilt from their stored history, through
   RecordAlertMetricsEvent. Alerts that already have one are untouched, so
   re-running gives the same numbers.

Runs where the worker runs (it uses the worker factories): on the host
against the local stack (the Make target), or inside a worker pod in OKD."""
from __future__ import annotations

import argparse
import logging
from datetime import date

from src.application.dtos.metrics_maintenance_dtos import BackfillAlertMetricsInput
from src.infrastructure.persistence.database.dynamodb.manager import (
    ensure_global_secondary_indexes,
)
from src.infrastructure.persistence.database.dynamodb.schemas import ALERTS_TABLE
from src.infrastructure.workflows.celery.factories import (
    get_alert_repository,
    get_backfill_alert_metrics_use_case,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--from", dest="from_day", required=True, type=date.fromisoformat)
    parser.add_argument("--to", dest="to_day", required=True, type=date.fromisoformat)
    args = parser.parse_args(argv)
    if args.to_day < args.from_day:
        parser.error("--to must be on or after --from")
    logging.basicConfig(level=logging.INFO)

    ensure_global_secondary_indexes(ALERTS_TABLE)
    filled = get_alert_repository().fill_missing_created_day(args.from_day, args.to_day)
    output = get_backfill_alert_metrics_use_case().execute(
        BackfillAlertMetricsInput(from_day=args.from_day, to_day=args.to_day)
    )
    print(
        f"metrics-backfill {args.from_day}..{args.to_day}: "
        f"created_day filled={filled} days={output.days} "
        f"alerts={output.alerts_seen} backfilled={output.backfilled} "
        f"already_recorded={output.already_recorded}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
