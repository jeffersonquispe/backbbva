from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta
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
    target_field: str = ""
    marking_date_field: str = ""
    label_value_mapping: dict[str, str] | None = None
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


def is_mature(
    alert: Any,
    *,
    as_of: date,
    maturing_days: int,
    target_field: str = "",
    marking_date_field: str = "",
    label_value_mapping: dict[str, str] | None = None,
) -> bool:
    if target_field and marking_date_field and label_value_mapping is not None:
        label = mapped_alert_label(alert, target_field, label_value_mapping)
        marked_at = alert_field_date(alert, marking_date_field)
        return bool(
            label in {"fraud", "no_fraud"}
            and marked_at is not None
            and marked_at <= as_of - timedelta(days=maturing_days)
        )
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
    values = []
    for field_name in fields:
        value = alert_field_value(alert, field_name)
        if value is None and metrics:
            value = getattr(metrics, field_name, None)
        values.append(str(getattr(value, "value", value) or "unknown"))
    return tuple(values)


def deterministic_sample(alerts: list[Any], spec: MatureSampleSpec) -> list[Any]:
    """Seeded, deterministic sampling with optional proportional stratification."""
    spec.validate()
    eligible = [
        alert
        for alert in alerts
        if spec.period_start <= alert.created_at.date() <= spec.period_end
        and is_mature(
            alert,
            as_of=spec.as_of,
            maturing_days=spec.maturing_days,
            target_field=spec.target_field,
            marking_date_field=spec.marking_date_field,
            label_value_mapping=spec.label_value_mapping,
        )
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
    if spec.target_field and spec.label_value_mapping is not None:
        fraud = [
            item
            for item in eligible
            if mapped_alert_label(item, spec.target_field, spec.label_value_mapping)
            == "fraud"
        ]
    else:
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


def normalize_label_value(value: Any) -> str:
    return str(getattr(value, "value", value) or "").strip().casefold()


def mapped_alert_label(
    alert: Any, target_field: str, label_value_mapping: dict[str, str]
) -> str | None:
    raw_value = alert_field_value(alert, target_field)
    normalized = normalize_label_value(raw_value)
    mapping = {normalize_label_value(key): value for key, value in label_value_mapping.items()}
    return mapping.get(normalized)


def alert_field_value(alert: Any, field_name: str) -> Any:
    labels = getattr(alert, "labels", {}) or {}
    if field_name in labels:
        return labels[field_name]
    source = getattr(alert, "input", {}) or {}
    if field_name in source:
        return source[field_name]
    current: Any = source
    for part in field_name.split("."):
        if isinstance(current, list):
            current = current[0] if current else None
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    if isinstance(current, list):
        current = current[0] if current else None
    return current


def alert_field_date(alert: Any, field_name: str) -> date | None:
    value = alert_field_value(alert, field_name)
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return None
        try:
            return datetime.fromisoformat(normalized.replace("Z", "+00:00")).date()
        except ValueError:
            try:
                return date.fromisoformat(normalized)
            except ValueError:
                return None
    return None
