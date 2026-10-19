from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any


@dataclass(frozen=True)
class MatureSampleSpec:
    as_of: date
    period_start: date
    period_end: date
    maturing_days: int
    sample_size: int
    seed: int
    strata: tuple[str, ...] = ()
    minimum_per_stratum: int = 0
    fraud_oversampling_ratio: float = 1.0
    train_proportion: float = 0.6
    validation_proportion: float = 0.2
    test_proportion: float = 0.2

    def validate(self) -> None:
        if self.period_end < self.period_start:
            raise ValueError("period_end debe ser igual o posterior a period_start")
        if self.maturing_days < 0 or self.sample_size < 1:
            raise ValueError("maturing_days y sample_size deben ser válidos")
        if self.minimum_per_stratum < 0 or self.fraud_oversampling_ratio < 1:
            raise ValueError("Parámetros de estrato/sobremuestreo inválidos")
        proportions = (
            self.train_proportion,
            self.validation_proportion,
            self.test_proportion,
        )
        if any(value < 0 or value > 1 for value in proportions) or abs(sum(proportions) - 1) > 1e-9:
            raise ValueError("Las proporciones deben sumar 1")


def is_mature(alert: Any, *, as_of: date, maturing_days: int) -> bool:
    metrics = getattr(alert, "metrics", None)
    label = getattr(metrics, "fraud_label", None)
    label_value = getattr(label, "value", label)
    return bool(
        metrics
        and label_value in {"fraud", "no_fraud"}
        and alert.created_at.date() <= as_of - timedelta(days=maturing_days)
    )


def stratum_key(alert: Any, fields: tuple[str, ...]) -> tuple[str, ...]:
    metrics = getattr(alert, "metrics", None)
    input_fields = getattr(alert, "input", {}) or {}
    values = []
    for field_name in fields:
        value = getattr(metrics, field_name, None) if metrics else None
        if value is None:
            value = input_fields.get(field_name)
        values.append(str(getattr(value, "value", value) or "unknown"))
    return tuple(values)


def deterministic_sample(alerts: list[Any], spec: MatureSampleSpec) -> list[Any]:
    """Seeded, deterministic sampling with optional proportional stratification."""
    spec.validate()
    eligible = [
        alert
        for alert in alerts
        if spec.period_start <= alert.created_at.date() <= spec.period_end
        and is_mature(alert, as_of=spec.as_of, maturing_days=spec.maturing_days)
    ]
    rng = random.Random(spec.seed)
    groups: dict[tuple[str, ...], list[Any]] = {}
    for alert in eligible:
        groups.setdefault(stratum_key(alert, spec.strata), []).append(alert)
    selected: list[Any] = []
    for key in sorted(groups):
        group = sorted(groups[key], key=lambda item: str(item.id))
        rng.shuffle(group)
        capacity = max(spec.minimum_per_stratum, round(spec.sample_size * len(group) / max(1, len(eligible))))
        selected.extend(group[:capacity])
    # Fraud oversampling is capped by the requested size and the eligible pool.
    fraud = [item for item in eligible if stratum_key(item, ("fraud_label",)) == ("fraud",)]
    if spec.fraud_oversampling_ratio > 1 and fraud:
        desired = min(len(fraud), round(spec.sample_size * spec.fraud_oversampling_ratio / (1 + spec.fraud_oversampling_ratio)))
        selected_ids = {str(item.id) for item in selected}
        extra = [item for item in fraud if str(item.id) not in selected_ids]
        rng.shuffle(extra)
        selected.extend(extra[:max(0, desired - sum(1 for item in selected if item in fraud))])
    rng.shuffle(selected)
    return selected[: spec.sample_size]


def deterministic_partition(alert_id: str, spec: MatureSampleSpec) -> str:
    value = int(hashlib.sha256(f"{spec.seed}:{alert_id}".encode()).hexdigest()[:16], 16) / 0xFFFFFFFFFFFFFFFF
    if value < spec.train_proportion:
        return "training"
    if value < spec.train_proportion + spec.validation_proportion:
        return "validation"
    # The settings contract exposes one holdout proportion. Split it evenly:
    # `test` is used for calibration and `final` remains reserved for evaluation.
    test_boundary = spec.train_proportion + spec.validation_proportion
    test_half = spec.test_proportion / 2
    return "test" if value < test_boundary + test_half else "final"


def content_hash(partitions: dict[str, list[dict[str, Any]]]) -> str:
    payload = json.dumps(partitions, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode()).hexdigest()
