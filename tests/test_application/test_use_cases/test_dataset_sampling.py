from __future__ import annotations

import random
from collections import Counter

import pytest

from src.application.use_cases.test_runs.dataset_sampling import (
    InsufficientSampleDataError,
    filter_rows,
    sample_percentage,
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


def test_filter_rows_single_filter() -> None:
    rows = [
        {"id": "a", "region": "north"},
        {"id": "b", "region": "south"},
        {"id": "c", "region": "north"},
    ]

    filtered = filter_rows(rows, {"region": "north"})

    assert [r["id"] for r in filtered] == ["a", "c"]


def test_filter_rows_multiple_and_combined_filters() -> None:
    rows = [
        {"id": "a", "region": "north", "tipo": "fraud"},
        {"id": "b", "region": "north", "tipo": "legit"},
        {"id": "c", "region": "south", "tipo": "fraud"},
    ]

    filtered = filter_rows(rows, {"region": "north", "tipo": "fraud"})

    assert [r["id"] for r in filtered] == ["a"]


def test_filter_rows_on_nested_dotted_field() -> None:
    rows = [
        {"id": "a", "object": {"integrationPoint": "web"}},
        {"id": "b", "object": {"integrationPoint": "mobile"}},
    ]

    filtered = filter_rows(rows, {"object.integrationPoint": "web"})

    assert [r["id"] for r in filtered] == ["a"]


def test_filter_rows_empty_filters_matches_every_row() -> None:
    rows = [{"id": "a"}, {"id": "b"}]

    filtered = filter_rows(rows, {})

    assert filtered == rows


def test_filter_rows_no_matches_returns_empty_list() -> None:
    rows = [{"id": "a", "region": "north"}]

    filtered = filter_rows(rows, {"region": "south"})

    assert filtered == []


def test_sample_percentage_returns_correct_count() -> None:
    rows = [{"id": i} for i in range(20)]

    sampled = sample_percentage(rows, 50, rng=random.Random(0))

    assert len(sampled) == 10
    # every sampled row must come from the source rows, no duplicates
    ids = [r["id"] for r in sampled]
    assert len(set(ids)) == len(ids)
    assert set(ids) <= {r["id"] for r in rows}


def test_sample_percentage_rejects_zero_percentage() -> None:
    with pytest.raises(ValueError, match="0"):
        sample_percentage([{"id": 1}], 0)


def test_sample_percentage_rejects_over_100_percentage() -> None:
    with pytest.raises(ValueError, match="101"):
        sample_percentage([{"id": 1}], 101)


def test_sample_percentage_empty_rows_returns_empty_list() -> None:
    assert sample_percentage([], 50) == []


def test_composed_filter_then_sample_percentage() -> None:
    rows = _rows({"no-risk": 40, "risk": 10}) + [
        {"id": f"other-{i}", "marcacion_final": "risk", "region": "east"}
        for i in range(10)
    ]
    # tag half the "risk" rows as region "west" to filter on
    for i, row in enumerate(r for r in rows if r["marcacion_final"] == "risk"):
        row["region"] = "west" if i < 10 else row.get("region", "east")

    filtered = filter_rows(rows, {"marcacion_final": "risk", "region": "west"})
    sampled = sample_percentage(filtered, 50, rng=random.Random(0))

    assert len(filtered) == 10
    assert len(sampled) == 5
    assert all(r["marcacion_final"] == "risk" and r["region"] == "west" for r in sampled)
