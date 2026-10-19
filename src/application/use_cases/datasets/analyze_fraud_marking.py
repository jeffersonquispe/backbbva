from __future__ import annotations

import random
import uuid
from collections.abc import Callable
from dataclasses import asdict, replace
from datetime import datetime

from src.application.dtos.dataset_dtos import (
    FraudMarkingAnalysisInput,
    FraudMarkingAnalysisOutput,
    FraudMaturationProfile,
)
from src.application.ports.async_operation_port import (
    AsyncOperationRecord,
    AsyncOperationRepository,
    AsyncOperationStatus,
)
from src.application.ports.clock_port import Clock
from src.application.ports.dataset_analysis_port import DatasetSummaryRepository
from src.application.ports.dataset_port import DatasetRepository
from src.application.ports.id_generator_port import IdGenerator
from src.application.runtime_defaults import (
    DEFAULT_ID_GENERATOR,
    resolve_clock,
)
from src.application.use_cases.datasets.field_extraction import get_nested_value


def _parse_timestamp(raw: str | None) -> datetime | None:
    if raw is None:
        return None
    try:
        return datetime.fromisoformat(raw.strip())
    except ValueError:
        return None


def _percentile(sorted_values: list[float], pct: float) -> float:
    """Linear-interpolation percentile (numpy's default "linear" method)
    over an already-sorted list. pct in [0, 100]."""
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (pct / 100) * (len(sorted_values) - 1)
    low = int(rank)
    high = min(low + 1, len(sorted_values) - 1)
    fraction = rank - low
    return sorted_values[low] + (sorted_values[high] - sorted_values[low]) * fraction


class AnalyzeFraudMarkingUseCase:
    """Compares a dataset's first/second fraud marks to flag false
    positives, false negatives and properly-marked rows, and profiles how
    long each row took to mature from the first mark to the second.

    On-demand and read-only: computed straight off DatasetRepository.get_rows
    every call, nothing is persisted (unlike DatasetSummaryRecord's stored
    field_distributions) - field names and the "positive" value are caller
    supplied since they vary per dataset export, not fixed columns.
    """

    def __init__(
        self,
        dataset_repository: DatasetRepository,
        summary_repository: DatasetSummaryRepository | None = None,
        async_operation_repository: AsyncOperationRepository | None = None,

        clock: Clock | None = None,
        id_generator: IdGenerator | None = None
    ) -> None:
        self._datasets = dataset_repository
        self._summaries = summary_repository
        self._operations = async_operation_repository
        self._clock = resolve_clock(clock)
        self._id_generator = id_generator or DEFAULT_ID_GENERATOR

    def schedule(self, input: FraudMarkingAnalysisInput) -> uuid.UUID | None:
        """Create the durable tracker for a worker-side marking analysis."""
        if self._operations is None:
            return None
        now = self._clock.now()
        operation_id = self._id_generator.new_id()
        self._operations.create(
            AsyncOperationRecord(
                id=operation_id,
                operation_type="dataset.fraud_marking_analyze",
                status=AsyncOperationStatus.PENDING,
                payload={
                    "dataset_name": input.dataset_name,
                    "first_mark_field": input.first_mark_field,
                    "second_mark_field": input.second_mark_field,
                    "first_mark_time_field": input.first_mark_time_field,
                    "second_mark_time_field": input.second_mark_time_field,
                    "positive_values": input.positive_values,
                },
                result={"stage": "queued", "progress_pct": 0},
                error=None,
                created_at=now,
                updated_at=now,
            )
        )
        return operation_id

    def execute(
        self,
        input: FraudMarkingAnalysisInput,
        progress: Callable[[dict[str, int | str]], None] | None = None,
    ) -> FraudMarkingAnalysisOutput:
        iter_rows = getattr(self._datasets, "iter_rows", None)
        rows = (
            iter_rows(input.dataset_name)
            if callable(iter_rows)
            else self._datasets.get_rows(input.dataset_name)
        )
        positive_values = frozenset(input.positive_values)
        summary = self._summaries.get(input.dataset_name) if self._summaries else None
        total_rows = summary.total_rows if summary is not None else 0

        evaluated_rows = 0
        skipped_rows = 0
        false_positives = 0
        false_negatives = 0
        properly_marked = 0
        # A bounded reservoir keeps percentile memory flat on multi-GB CSVs.
        duration_sample: list[float] = []
        duration_count = 0
        randomizer = random.Random(input.dataset_name)

        processed_rows = 0
        reported_progress = -1
        for row in rows:
            processed_rows += 1
            # Reporting at most once per percentage point keeps DynamoDB
            # writes bounded while giving the UI meaningful task progress.
            if progress is not None and total_rows > 0:
                progress_pct = min(99, max(1, int(processed_rows * 100 / total_rows)))
                if progress_pct > reported_progress:
                    progress(
                        {
                            "stage": "scanning_rows",
                            "progress_pct": progress_pct,
                            "processed_rows": processed_rows,
                            "total_rows": total_rows,
                        }
                    )
                    reported_progress = progress_pct
            first_mark = get_nested_value(row, input.first_mark_field)
            second_mark = get_nested_value(row, input.second_mark_field)
            if first_mark is None or second_mark is None:
                skipped_rows += 1
                continue
            evaluated_rows += 1

            # Membership, not equality - a row moving between two different
            # positive labels (e.g. "risk-suspected" -> "risk") is both
            # "first positive" and "second positive" here, so it falls into
            # properly_marked below rather than false_positives/negatives -
            # it isn't a real remark, just an escalation within the
            # positive class.
            first_positive = first_mark in positive_values
            second_positive = second_mark in positive_values
            if first_positive and not second_positive:
                false_positives += 1
            elif not first_positive and second_positive:
                false_negatives += 1
            else:
                properly_marked += 1

            first_time = _parse_timestamp(
                get_nested_value(row, input.first_mark_time_field)
            )
            second_time = _parse_timestamp(
                get_nested_value(row, input.second_mark_time_field)
            )
            if first_time is not None and second_time is not None:
                delta_days = (second_time - first_time).total_seconds() / 86_400
                if delta_days >= 0:
                    duration_count += 1
                    if len(duration_sample) < 100_000:
                        duration_sample.append(delta_days)
                    else:
                        replacement = randomizer.randrange(duration_count)
                        if replacement < len(duration_sample):
                            duration_sample[replacement] = delta_days

        if duration_sample:
            duration_sample.sort()
            maturation = FraudMaturationProfile(
                sample_size=duration_count,
                avg_days=round(sum(duration_sample) / len(duration_sample), 2),
                min_days=round(duration_sample[0], 2),
                max_days=round(duration_sample[-1], 2),
                p50_days=round(_percentile(duration_sample, 50), 2),
                p75_days=round(_percentile(duration_sample, 75), 2),
                p90_days=round(_percentile(duration_sample, 90), 2),
                p95_days=round(_percentile(duration_sample, 95), 2),
                p98_days=round(_percentile(duration_sample, 98), 2),
                p99_days=round(_percentile(duration_sample, 99), 2),
            )
        else:
            maturation = FraudMaturationProfile(sample_size=0)

        output = FraudMarkingAnalysisOutput(
            dataset_name=input.dataset_name,
            evaluated_rows=evaluated_rows,
            skipped_rows=skipped_rows,
            false_positives=false_positives,
            false_negatives=false_negatives,
            properly_marked=properly_marked,
            maturation=maturation,
        )
        if self._summaries is not None:
            summary = self._summaries.get(input.dataset_name)
            if summary is not None:
                config = {
                    "first_mark_field": input.first_mark_field,
                    "second_mark_field": input.second_mark_field,
                    "first_mark_time_field": input.first_mark_time_field,
                    "second_mark_time_field": input.second_mark_time_field,
                    "positive_values": input.positive_values,
                }
                self._summaries.upsert(replace(
                    summary,
                    fraud_marking_analysis=asdict(output),
                    fraud_marking_analysis_config=config,
                ))
        return output
