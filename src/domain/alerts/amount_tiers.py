"""Amount tiers: the admin-configured ranges an alert's amount is classified
into (OperationalSettings.amount_tiers). The tier is computed once, when the
alert arrives, and frozen on its metrics snapshot - changing the tiers only
affects new alerts (see docs/OBSERVABILITY_STRATEGY.md)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

# Every amount classifies as this when no tiers are configured, the amount
# is missing/unparseable, or it falls outside every tier (negative).
UNKNOWN_AMOUNT_TIER = "unknown"


@dataclass(frozen=True)
class AmountTier:
    code: str
    label: str
    min_inclusive: float
    # None = no upper bound (the last tier, up to infinity).
    max_exclusive: float | None = None


class InvalidAmountTiersError(ValueError):
    """The tier set is not a contiguous, non-overlapping cover of 0 -> inf."""


def validate_amount_tiers(tiers: list[AmountTier]) -> None:
    """An empty list is valid (every amount is "unknown"). Otherwise, sorted
    by min_inclusive, the tiers must start at 0, each one must end exactly
    where the next starts, and only the last one may be unbounded."""
    if not tiers:
        return
    codes = [tier.code for tier in tiers]
    if any(not code.strip() for code in codes):
        raise InvalidAmountTiersError("Every amount tier needs a non-empty code.")
    if len(set(codes)) != len(codes):
        raise InvalidAmountTiersError("Amount tier codes must be unique.")
    if UNKNOWN_AMOUNT_TIER in codes:
        raise InvalidAmountTiersError(
            f"{UNKNOWN_AMOUNT_TIER!r} is reserved and cannot be a tier code."
        )
    ordered = sorted(tiers, key=lambda tier: tier.min_inclusive)
    if ordered[0].min_inclusive != 0:
        raise InvalidAmountTiersError("The first amount tier must start at 0.")
    for current, following in zip(ordered, ordered[1:]):
        if current.max_exclusive is None:
            raise InvalidAmountTiersError(
                f"Only the last amount tier may be unbounded ({current.code!r} is not last)."
            )
        if current.max_exclusive != following.min_inclusive:
            raise InvalidAmountTiersError(
                f"Amount tiers {current.code!r} and {following.code!r} must be "
                "contiguous (no gaps, no overlaps)."
            )
    for tier in ordered:
        if tier.max_exclusive is not None and tier.max_exclusive <= tier.min_inclusive:
            raise InvalidAmountTiersError(
                f"Amount tier {tier.code!r} must end above where it starts."
            )
    if ordered[-1].max_exclusive is not None:
        raise InvalidAmountTiersError(
            "The last amount tier must be unbounded (up to infinity)."
        )


def classify_amount(amount: Any, tiers: list[AmountTier]) -> str:
    """Tier code for the amount, or "unknown" when it can't be classified.
    Accepts numbers or numeric strings (payload values arrive either way)."""
    value = parse_amount(amount)
    if value is None or value < 0:
        return UNKNOWN_AMOUNT_TIER
    for tier in tiers:
        if value >= tier.min_inclusive and (
            tier.max_exclusive is None or value < tier.max_exclusive
        ):
            return tier.code
    return UNKNOWN_AMOUNT_TIER


def parse_amount(value: Any) -> float | None:
    """A finite float from a number or numeric string; None otherwise."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value.strip()) if isinstance(value, str) else float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None
