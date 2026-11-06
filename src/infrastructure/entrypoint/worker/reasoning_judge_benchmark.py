"""Measure how long the LLM-judge takes with the REAL model, and project whether
the evaluator keeps up:

    make reasoning-judge-benchmark SAMPLES=8 ALERTS_PER_DAY=1600 WORKERS=1

Runs inside the evaluator's worker container (it needs the LLM credentials and the
worker factories). It re-judges alerts that already have a verdict, WITHOUT storing
or counting anything, so it changes no data - it only spends the tokens it reports.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from src.application.use_cases.metrics.reasoning_judge_timing import (
    JudgeCall,
    summarize,
)
from src.infrastructure.core.config import genai_config
from src.infrastructure.workflows.celery.factories import (
    get_alert_reasoning_evaluation_repository,
    get_evaluate_alert_reasoning_use_case,
    get_operational_settings_repository,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument(
        "--days", type=int, default=7, help="look-back for judged alerts"
    )
    parser.add_argument("--alerts-per-day", type=float, default=1600)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--peak-factor", type=float, default=3.0)
    parser.add_argument("--sample-rate", type=float, default=None)
    args = parser.parse_args(argv)

    # Verdict days are Bogotá days, not the container's (UTC) day.
    today = datetime.now(ZoneInfo(genai_config.OPERATIONS_TIMEZONE)).date()
    judged = get_alert_reasoning_evaluation_repository().list_between(
        today - timedelta(days=args.days), today, limit=args.samples
    )
    if not judged:
        print(
            "No hay alertas ya evaluadas en el periodo para re-evaluar. Procesa "
            "alertas con muestreo (o pide una evaluación) y vuelve a intentarlo.",
            file=sys.stderr,
        )
        return 1
    rate = (
        args.sample_rate
        if args.sample_rate is not None
        else get_operational_settings_repository()
        .get()
        .reasoning_evaluation_sample_rate
    )
    use_case = get_evaluate_alert_reasoning_use_case()
    calls: list[JudgeCall] = []
    for index, record in enumerate(judged, 1):
        started = time.perf_counter()
        fresh = use_case.judge_only(record.alert_id, record.workflow_execution_id)
        wall_ms = int((time.perf_counter() - started) * 1000)
        if fresh is None:
            print(f"  {index}/{len(judged)} {record.alert_id}: nada que juzgar")
            continue
        calls.append(
            JudgeCall(
                duration_ms=wall_ms,
                input_tokens=fresh.input_tokens,
                output_tokens=fresh.output_tokens,
                attempts=fresh.attempts,
            )
        )
        print(
            f"  {index}/{len(judged)} {record.alert_id}: {wall_ms} ms, "
            f"{fresh.input_tokens + fresh.output_tokens} tokens, "
            f"{fresh.attempts} intento(s), {fresh.status.value}"
        )
    if not calls:
        return 1
    report = summarize(
        calls,
        alerts_per_day=args.alerts_per_day,
        sample_rate=rate,
        workers=args.workers,
        peak_factor=args.peak_factor,
    )

    def wait(projection) -> str:
        if not projection.keeps_up:
            return "NO da abasto (la cola crece)"
        return f"espera media {projection.expected_wait_s:.1f} s"

    print(
        f"\nCada evaluación: p50 {report.p50_ms} ms · p95 {report.p95_ms} ms · "
        f"máx {report.max_ms} ms · ~{report.mean_tokens:.0f} tokens "
        f"({report.retried_share:.0%} con reintento)\n"
        f"Carga: {args.alerts_per_day:.0f} alertas/día × muestreo {rate:.0%} = "
        f"{report.evaluations_per_day:.0f} evaluaciones/día "
        f"(~{report.tokens_per_day:,.0f} tokens/día)\n"
        f"Capacidad con {args.workers} worker(s): {report.hourly_capacity:.0f} evaluaciones/hora\n"
        f"Hora promedio ({report.average_hour.arrivals_per_hour:.1f}/h): "
        f"utilización {report.average_hour.utilization:.0%}, {wait(report.average_hour)}\n"
        f"Hora pico ×{args.peak_factor:g} ({report.peak_hour.arrivals_per_hour:.1f}/h): "
        f"utilización {report.peak_hour.utilization:.0%}, {wait(report.peak_hour)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
