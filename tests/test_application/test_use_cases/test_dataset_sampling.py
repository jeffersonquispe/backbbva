from __future__ import annotations

import random
from collections import Counter

import pytest

from src.application.use_cases.test_runs.dataset_sampling import (
    InsufficientSampleDataError,
    sample_rows,
)


def _rows(counts: dict[str, int]) -> list[dict]:
    rows = []
    for marcacion, n in counts.items():
        for i in range(n):
            rows.append({"id": f"{marcacion}-{i}", "marcacion_final": marcacion})
    return rows


def test_natural_distribution_mirrors_source_proportions() -> None:
    rows = _rows({"no-risk": 80, "risk-suspected": 15, "risk": 5})

    sampled = sample_rows(rows, size=20, rng=random.Random(0))

    counts = Counter(r["marcacion_final"] for r in sampled)
    assert counts == {"no-risk": 16, "risk-suspected": 3, "risk": 1}


def test_explicit_distribution_overrides_natural_shape() -> None:
    rows = _rows({"no-risk": 80, "risk-suspected": 15, "risk": 5})

    sampled = sample_rows(
        rows,
        size=10,
        distribution={"no-risk": 0.34, "risk-suspected": 0.33, "risk": 0.33},
        rng=random.Random(0),
    )

    counts = Counter(r["marcacion_final"] for r in sampled)
    # Largest-remainder rounding of 3.4/3.3/3.3 -> 4/3/3 (no-risk's 0.4
    # remainder beats the other two's 0.3), not naive floor (3/3/3, which
    # would only sum to 9).
    assert counts == {"no-risk": 4, "risk-suspected": 3, "risk": 3}
    assert sum(counts.values()) == 10


def test_raises_when_a_class_does_not_have_enough_rows() -> None:
    rows = _rows({"no-risk": 5, "risk-suspected": 1, "risk": 1})

    with pytest.raises(InsufficientSampleDataError) as exc_info:
        sample_rows(
            rows,
            size=10,
            distribution={"no-risk": 0.34, "risk-suspected": 0.33, "risk": 0.33},
        )

    assert "risk-suspected" in exc_info.value.shortfalls
    assert "risk" in exc_info.value.shortfalls
    assert "no-risk" not in exc_info.value.shortfalls


def test_rejects_unknown_class_in_distribution() -> None:
    rows = _rows({"no-risk": 5})

    with pytest.raises(ValueError, match="Unknown marcación class"):
        sample_rows(rows, size=1, distribution={"totally-fake": 1.0})


def test_rejects_distribution_not_summing_to_one() -> None:
    rows = _rows({"no-risk": 5, "risk": 5})

    with pytest.raises(ValueError, match="must sum to 1.0"):
        sample_rows(rows, size=1, distribution={"no-risk": 0.5, "risk": 0.2})


def test_rows_with_unknown_or_missing_marcacion_are_excluded() -> None:
    rows = _rows({"no-risk": 3}) + [
        {"id": "x", "marcacion_final": "not-a-real-class"},
        {"id": "y"},
    ]

    sampled = sample_rows(rows, size=2, rng=random.Random(0))

    assert len(sampled) == 2
    assert all(r["marcacion_final"] == "no-risk" for r in sampled)


def test_result_size_always_matches_request_across_uneven_percentages() -> None:
    rows = _rows({"no-risk": 100, "risk-suspected": 100, "risk": 100})

    for size in range(1, 30):
        sampled = sample_rows(rows, size=size, rng=random.Random(size))
        assert len(sampled) == size
