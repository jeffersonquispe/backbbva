from datetime import UTC, datetime, timedelta

from hypothesis import given
from hypothesis import strategies as st

from src.domain.alerts.transaction_history_selection import select_transaction_history


@given(
    offsets=st.lists(
        st.integers(min_value=0, max_value=100_000),
        min_size=1,
        max_size=80,
        unique=True,
    ),
    limit=st.integers(min_value=1, max_value=80),
)
def test_selection_is_newest_first_and_respects_limit(
    offsets: list[int], limit: int
) -> None:
    anchor = datetime(2026, 10, 25, tzinfo=UTC)
    entries = [
        {
            "event_id": str(offset),
            "event_time": (anchor - timedelta(seconds=offset)).isoformat(),
        }
        for offset in offsets
    ]

    selected = select_transaction_history(
        entries,
        columns=[],
        window_days=0,
        max_transactions=limit,
        reference_time=anchor,
    )

    selected_times = [datetime.fromisoformat(row["event_time"]) for row in selected]
    assert len(selected) == min(limit, len(entries))
    assert selected_times == sorted(selected_times, reverse=True)
    assert {row["event_id"] for row in selected} <= {str(offset) for offset in offsets}
