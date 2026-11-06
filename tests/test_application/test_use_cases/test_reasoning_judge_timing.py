from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from src.application.use_cases.metrics.reasoning_judge_timing import (
    JudgeCall,
    percentile,
    project_load,
    summarize,
)


def test_percentiles_use_the_nearest_rank() -> None:
    values = [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000]

    assert percentile(values, 0.5) == 500
    assert percentile(values, 0.95) == 1000
    assert percentile([42], 0.95) == 42
    assert percentile([], 0.5) == 0


def test_one_worker_matches_the_textbook_mm1_queue() -> None:
    # M/M/1: utilization rho, mean wait in queue = rho * service / (1 - rho).
    projection = project_load(mean_service_s=10, workers=1, arrivals_per_hour=180)

    assert projection.utilization == pytest.approx(0.5)
    assert projection.expected_wait_s == pytest.approx(0.5 * 10 / (1 - 0.5))
    assert projection.keeps_up


def test_more_workers_cut_the_wait() -> None:
    one = project_load(10, 1, 270)
    two = project_load(10, 2, 270)

    assert one.keeps_up and two.keeps_up
    assert two.expected_wait_s < one.expected_wait_s
    assert two.utilization == pytest.approx(one.utilization / 2)


def test_an_overloaded_evaluator_is_reported_as_not_keeping_up() -> None:
    projection = project_load(mean_service_s=10, workers=1, arrivals_per_hour=400)

    assert projection.utilization > 1
    assert projection.expected_wait_s is None and not projection.keeps_up


def test_no_arrivals_means_no_wait() -> None:
    projection = project_load(10, 1, 0)

    assert (projection.utilization, projection.expected_wait_s) == (0.0, 0.0)


def test_invalid_inputs_are_rejected() -> None:
    with pytest.raises(ValueError):
        project_load(0, 1, 10)
    with pytest.raises(ValueError):
        project_load(10, 0, 10)
    with pytest.raises(ValueError):
        summarize([], alerts_per_day=100, sample_rate=0.05, workers=1)


def test_the_report_projects_the_daily_load_and_the_peak_hour() -> None:
    calls = [
        JudgeCall(duration_ms=ms, input_tokens=900, output_tokens=100)
        for ms in (8000, 10000, 12000)
    ]
    calls.append(JudgeCall(30000, 1800, 200, attempts=2))

    report = summarize(calls, alerts_per_day=1600, sample_rate=0.05, workers=1)

    assert (report.calls, report.p50_ms, report.max_ms) == (4, 10000, 30000)
    assert report.mean_ms == pytest.approx(15000)
    assert report.retried_share == pytest.approx(0.25)
    assert report.evaluations_per_day == pytest.approx(80)
    assert report.tokens_per_day == pytest.approx(80 * (1000 + 1000 + 1000 + 2000) / 4)
    assert report.hourly_capacity == pytest.approx(3600 / 15)
    # 80/day = 3.33/h on average, x3 at peak: well within one worker's 240/h.
    assert report.average_hour.arrivals_per_hour == pytest.approx(80 / 24)
    assert report.peak_hour.arrivals_per_hour == pytest.approx(80 / 24 * 3)
    assert report.average_hour.keeps_up and report.peak_hour.keeps_up
    assert report.peak_hour.expected_wait_s > report.average_hour.expected_wait_s


def test_a_sample_rate_outside_zero_one_is_clamped() -> None:
    calls = [JudgeCall(1000, 10, 10)]

    assert (
        summarize(
            calls, alerts_per_day=100, sample_rate=5, workers=1
        ).evaluations_per_day
        == 100
    )
    assert (
        summarize(
            calls, alerts_per_day=100, sample_rate=-1, workers=1
        ).evaluations_per_day
        == 0
    )


@given(
    service=st.floats(min_value=0.5, max_value=120),
    workers=st.integers(min_value=1, max_value=8),
    arrivals=st.floats(min_value=0, max_value=5000),
)
def test_utilization_and_wait_are_consistent(
    service: float, workers: int, arrivals: float
) -> None:
    projection = project_load(service, workers, arrivals)

    assert projection.utilization >= 0
    assert projection.keeps_up == (projection.utilization < 1)
    if projection.keeps_up:
        assert (
            projection.expected_wait_s is not None and projection.expected_wait_s >= 0
        )
    else:
        assert projection.expected_wait_s is None
