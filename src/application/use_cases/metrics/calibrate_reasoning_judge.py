"""Calibrating the LLM-judge against people (PENDIENTES evaluator 4).

Two pure steps, so the maths is testable without a database:

* ``review_sample``: a reproducible random sample of judged alerts to hand to
  reviewers, with the judge's verdict hidden from the order they are shown in.
* ``score``: agreement between the judge and the humans' answers, per criterion
  (hallucination, data_use_correct): accuracy, Cohen's kappa and the judge's false
  positives / false negatives taking the human as the truth.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from src.application.ports.alert_reasoning_evaluation_port import (
    AlertReasoningEvaluationRecord,
    ReasoningEvaluationStatus,
)

CRITERIA = ("hallucination", "data_use_correct")


def review_sample(
    records: list[AlertReasoningEvaluationRecord], size: int, seed: int
) -> list[AlertReasoningEvaluationRecord]:
    """Up to ``size`` valid verdicts, the same ones for the same seed."""
    valid = sorted(
        (r for r in records if r.status == ReasoningEvaluationStatus.EVALUATED),
        key=lambda r: str(r.alert_id),
    )
    if size >= len(valid):
        picked = list(valid)
    else:
        picked = random.Random(seed).sample(valid, size)
    random.Random(seed).shuffle(picked)
    return picked


@dataclass(frozen=True)
class CriterionAgreement:
    criterion: str
    compared: int
    agreement: float | None
    cohen_kappa: float | None
    # The judge said "true" and the human said "false", and the reverse.
    judge_true_human_false: int
    judge_false_human_true: int

    @property
    def usable(self) -> bool:
        """Rule of thumb for using the KPI: substantial agreement (kappa >= 0.6)."""
        return self.cohen_kappa is not None and self.cohen_kappa >= 0.6


def score(
    pairs: dict[str, list[tuple[bool, bool]]],
) -> list[CriterionAgreement]:
    """``pairs[criterion]`` = [(judge, human), ...] for the alerts the humans
    answered. Cohen's kappa corrects the agreement for what chance would give."""
    return [_agreement(name, pairs.get(name, [])) for name in CRITERIA]


def _agreement(criterion: str, pairs: list[tuple[bool, bool]]) -> CriterionAgreement:
    total = len(pairs)
    if total == 0:
        return CriterionAgreement(criterion, 0, None, None, 0, 0)
    both = sum(1 for judge, human in pairs if judge and human)
    neither = sum(1 for judge, human in pairs if not judge and not human)
    false_positive = sum(1 for judge, human in pairs if judge and not human)
    false_negative = sum(1 for judge, human in pairs if not judge and human)
    observed = (both + neither) / total
    judge_true = (both + false_positive) / total
    human_true = (both + false_negative) / total
    expected = judge_true * human_true + (1 - judge_true) * (1 - human_true)
    kappa = None if expected == 1 else (observed - expected) / (1 - expected)
    return CriterionAgreement(
        criterion, total, observed, kappa, false_positive, false_negative
    )
