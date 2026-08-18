from __future__ import annotations

import random
from typing import Any

# The 3 ground-truth values a dataset row's "marcacion_final" column can
# carry (analyst-labeled, see Muestra_total_ARIA.csv) - the only closed
# vocabulary this sampler knows about, matched exactly.
MARCACION_FIELD = "marcacion_final"
MARCACION_CLASSES = ("no-risk", "risk-suspected", "risk")


class InsufficientSampleDataError(Exception):
    """A requested class target exceeds how many rows of that class exist
    in the dataset - raised instead of silently returning fewer rows than
    asked for, since a caller building an evaluation sample needs to know
    its composition is exactly what it asked for."""

    def __init__(self, shortfalls: dict[str, tuple[int, int]]) -> None:
        self.shortfalls = shortfalls
        detail = ", ".join(
            f"{cls} (requested {requested}, only {available} available)"
            for cls, (requested, available) in shortfalls.items()
        )
        super().__init__(f"Not enough rows to satisfy the requested sample: {detail}")


def sample_rows(
    rows: list[dict[str, Any]],
    *,
    size: int,
    distribution: dict[str, float] | None = None,
    marcacion_field: str = MARCACION_FIELD,
    rng: random.Random | None = None,
) -> list[dict[str, Any]]:
    """Select `size` rows out of `rows`, stratified by marcacion_field.

    distribution=None: mirror the dataset's own observed proportions
    across the 3 marcación classes (no-risk / risk-suspected / risk) -
    "give me 100 samples shaped like this dataset".

    distribution={"risk": 0.5, "no-risk": 0.3, "risk-suspected": 0.2}:
    use these exact proportions instead, e.g. to build a class-balanced
    sample out of an imbalanced dataset. Must cover exactly the 3 known
    classes and sum to 1.0.

    Rows whose marcacion_field value isn't one of the 3 known classes are
    dropped from consideration entirely (can't stratify what isn't
    labeled) - not counted toward `size`.
    """
    rng = rng or random.Random()

    buckets: dict[str, list[dict[str, Any]]] = {cls: [] for cls in MARCACION_CLASSES}
    for row in rows:
        value = row.get(marcacion_field)
        if value in buckets:
            buckets[value].append(row)

    proportions = _resolve_proportions(buckets, distribution)
    targets = _allocate_counts(size, proportions)

    shortfalls = {
        cls: (target, len(buckets[cls]))
        for cls, target in targets.items()
        if target > len(buckets[cls])
    }
    if shortfalls:
        raise InsufficientSampleDataError(shortfalls)

    sampled: list[dict[str, Any]] = []
    for cls, target in targets.items():
        sampled.extend(rng.sample(buckets[cls], target))
    rng.shuffle(sampled)
    return sampled


def _resolve_proportions(
    buckets: dict[str, list[dict[str, Any]]],
    distribution: dict[str, float] | None,
) -> dict[str, float]:
    if distribution is None:
        total = sum(len(rows) for rows in buckets.values())
        if total == 0:
            return {cls: 0.0 for cls in MARCACION_CLASSES}
        return {cls: len(buckets[cls]) / total for cls in MARCACION_CLASSES}

    unknown = set(distribution) - set(MARCACION_CLASSES)
    if unknown:
        raise ValueError(
            f"Unknown marcación class(es) in distribution: {sorted(unknown)}"
        )
    total_pct = sum(distribution.values())
    if abs(total_pct - 1.0) > 1e-6:
        raise ValueError(
            f"distribution percentages must sum to 1.0, got {total_pct}"
        )
    return {cls: distribution.get(cls, 0.0) for cls in MARCACION_CLASSES}


def _allocate_counts(size: int, proportions: dict[str, float]) -> dict[str, int]:
    # Largest-remainder method: round each class's exact share down, then
    # hand out the leftover (lost to rounding) one-by-one to the classes
    # with the biggest fractional remainder - guarantees the counts sum
    # to exactly `size` instead of drifting from naive per-class rounding.
    exact = {cls: size * pct for cls, pct in proportions.items()}
    counts = {cls: int(v) for cls, v in exact.items()}
    leftover = size - sum(counts.values())
    by_remainder = sorted(
        exact, key=lambda cls: exact[cls] - counts[cls], reverse=True
    )
    for cls in by_remainder[:leftover]:
        counts[cls] += 1
    return counts
