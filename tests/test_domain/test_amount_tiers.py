from __future__ import annotations

import pytest

from src.domain.alerts.amount_tiers import (
    UNKNOWN_AMOUNT_TIER,
    AmountTier,
    InvalidAmountTiersError,
    classify_amount,
    validate_amount_tiers,
)

TIERS = [
    AmountTier(code="low", label="< 1M", min_inclusive=0, max_exclusive=1_000_000),
    AmountTier(code="mid", label="1M-3M", min_inclusive=1_000_000, max_exclusive=3_000_000),
    AmountTier(code="high", label="> 3M", min_inclusive=3_000_000, max_exclusive=None),
]


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        (0, "low"),
        (999_999.99, "low"),
        (1_000_000, "mid"),  # exact lower bound belongs to the upper tier
        (2_999_999, "mid"),
        (3_000_000, "high"),
        (10**12, "high"),
        ("1500000", "mid"),  # numeric strings from payloads
        (" 42.5 ", "low"),
    ],
)
def test_classify_amount_bounds(amount, expected) -> None:
    assert classify_amount(amount, TIERS) == expected


@pytest.mark.parametrize(
    "amount", [None, -1, -0.01, "", "abc", "1,5", float("nan"), float("inf"), True]
)
def test_classify_amount_unclassifiable_is_unknown(amount) -> None:
    assert classify_amount(amount, TIERS) == UNKNOWN_AMOUNT_TIER


def test_classify_amount_without_tiers_is_unknown() -> None:
    assert classify_amount(500, []) == UNKNOWN_AMOUNT_TIER


def test_validate_accepts_empty_and_unordered_contiguous_cover() -> None:
    validate_amount_tiers([])
    validate_amount_tiers(list(reversed(TIERS)))


@pytest.mark.parametrize(
    "tiers",
    [
        # gap between 1M and 2M
        [
            AmountTier("a", "a", 0, 1_000_000),
            AmountTier("b", "b", 2_000_000, None),
        ],
        # overlap
        [
            AmountTier("a", "a", 0, 2_000_000),
            AmountTier("b", "b", 1_000_000, None),
        ],
        # does not start at 0
        [AmountTier("a", "a", 10, None)],
        # last tier bounded (does not reach infinity)
        [AmountTier("a", "a", 0, 100)],
        # unbounded tier not last
        [AmountTier("a", "a", 0, None), AmountTier("b", "b", 0, 5)],
        # duplicate code
        [AmountTier("a", "a", 0, 10), AmountTier("a", "a", 10, None)],
        # reserved code
        [AmountTier("unknown", "x", 0, None)],
        # empty code
        [AmountTier(" ", "x", 0, None)],
        # empty range
        [AmountTier("a", "a", 0, 0), AmountTier("b", "b", 0, None)],
    ],
)
def test_validate_rejects_invalid_sets(tiers) -> None:
    with pytest.raises(InvalidAmountTiersError):
        validate_amount_tiers(tiers)
