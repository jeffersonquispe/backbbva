"""Calibrate the LLM-judge against human reviewers:

    make reasoning-judge-review-export FROM=2026-11-01 TO=2026-11-05 SIZE=40
    # reviewers fill human_hallucination / human_data_use_correct (yes|no)
    make reasoning-judge-review-score FILE=review.csv

``export`` writes a reproducible random sample of judged alerts (alert id,
rationale and per-step notes, WITHOUT the judge's verdict, so reviewers are not
anchored) plus the judge's verdicts in a separate key file. ``score`` joins the
filled sheet with that key and prints agreement, Cohen's kappa and the judge's
false positives / negatives per criterion.

Runs where the worker runs (worker factories): on the host against the local
stack, or inside a worker pod in OKD."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date
from pathlib import Path

from src.application.use_cases.metrics.calibrate_reasoning_judge import (
    CRITERIA,
    review_sample,
    score,
)
from src.infrastructure.workflows.celery.factories import (
    get_alert_reasoning_evaluation_repository,
)

_YES = {"si", "sí", "yes", "y", "true", "1", "x"}
_NO = {"no", "n", "false", "0"}


def _answer(value: str) -> bool | None:
    text = (value or "").strip().lower()
    if text in _YES:
        return True
    if text in _NO:
        return False
    return None


def export(args: argparse.Namespace) -> int:
    records = get_alert_reasoning_evaluation_repository().list_between(
        args.from_day, args.to_day, limit=5_000
    )
    sample = review_sample(records, args.size, args.seed)
    out = Path(args.out)
    with out.open("w", newline="", encoding="utf-8") as sheet:
        writer = csv.writer(sheet)
        writer.writerow(
            [
                "alert_id",
                "judge_rationale",
                "judge_step_notes",
                "human_hallucination",
                "human_data_use_correct",
                "human_comment",
            ]
        )
        for record in sample:
            notes = "; ".join(
                f"{name}: {verdict.get('note', '')}"
                for name, verdict in record.step_verdicts.items()
            )
            writer.writerow([record.alert_id, record.rationale, notes, "", "", ""])
    key = out.with_suffix(".key.json")
    key.write_text(
        json.dumps(
            {
                str(r.alert_id): {
                    "hallucination": r.hallucination,
                    "data_use_correct": r.data_use_correct,
                    "prompt_version": r.prompt_version,
                    "judge_model": r.judge_model,
                }
                for r in sample
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"{len(sample)} alertas -> {out} (clave del juez: {key})")
    return 0


def run_score(args: argparse.Namespace) -> int:
    sheet = Path(args.file)
    key = json.loads(sheet.with_suffix(".key.json").read_text(encoding="utf-8"))
    pairs: dict[str, list[tuple[bool, bool]]] = {name: [] for name in CRITERIA}
    with sheet.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            judged = key.get(row["alert_id"])
            if judged is None:
                continue
            for criterion, column in (
                ("hallucination", "human_hallucination"),
                ("data_use_correct", "human_data_use_correct"),
            ):
                human = _answer(row.get(column, ""))
                if human is not None and judged[criterion] is not None:
                    pairs[criterion].append((bool(judged[criterion]), human))
    prompts = sorted({entry["prompt_version"] for entry in key.values()})
    print(f"Versión(es) de prompt evaluadas: {', '.join(prompts)}")
    for result in score(pairs):
        kappa = "n/d" if result.cohen_kappa is None else f"{result.cohen_kappa:.2f}"
        agreement = "n/d" if result.agreement is None else f"{result.agreement:.0%}"
        print(
            f"{result.criterion}: {result.compared} comparadas · acuerdo {agreement} · "
            f"kappa {kappa} · juez=sí/humano=no {result.judge_true_human_false} · "
            f"juez=no/humano=sí {result.judge_false_human_true} · "
            f"{'usable' if result.usable else 'NO usable aún (kappa < 0,6)'}"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    exporter = commands.add_parser("export")
    exporter.add_argument(
        "--from", dest="from_day", required=True, type=date.fromisoformat
    )
    exporter.add_argument("--to", dest="to_day", required=True, type=date.fromisoformat)
    exporter.add_argument("--size", type=int, default=40)
    exporter.add_argument("--seed", type=int, default=1)
    exporter.add_argument("--out", default="reasoning-judge-review.csv")
    scorer = commands.add_parser("score")
    scorer.add_argument("--file", required=True)
    args = parser.parse_args(argv)
    return export(args) if args.command == "export" else run_score(args)


if __name__ == "__main__":
    sys.exit(main())
