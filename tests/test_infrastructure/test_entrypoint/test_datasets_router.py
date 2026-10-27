"""#23: split preview/create expose provenance, schema context and limits."""

from __future__ import annotations

from datetime import UTC, date, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.use_cases.datasets.append_dataset_rows import (
    AppendDatasetRowsUseCase,
)
from src.application.use_cases.datasets.prepare_dataset_split import (
    PrepareDatasetSplitUseCase,
)
from src.domain.datasets.mature_sample_entities import DatasetSnapshot
from src.infrastructure.entrypoint.api.factories.dataset_factory import (
    get_append_dataset_rows_use_case,
    get_prepare_dataset_split_use_case,
)
from src.infrastructure.entrypoint.api.fastapi_app import _register_error_handlers
from src.infrastructure.entrypoint.api.routers.datasets_router import router


class InMemoryDatasetRepository:
    def __init__(self, rows: dict[str, list[dict]]) -> None:
        self.rows = rows

    def list(self):
        return [type("Dataset", (), {"name": n, "row_count": len(r)})() for n, r in self.rows.items()]

    def get_rows(self, name):
        return [dict(row) for row in self.rows[name]]

    def get_fields(self, name):
        return list(self.rows[name][0])

    def create(self, name, fields):
        self.rows[name] = []

    def append_rows(self, name, rows):
        self.rows[name].extend(rows)
        return len(self.rows[name])

    def delete(self, name):
        self.rows.pop(name, None)


class InMemoryDatasetSummaryRepository:
    def __init__(self) -> None:
        self.rows: dict = {}

    def get(self, name):
        return self.rows.get(name)

    def upsert(self, summary):
        self.rows[summary.dataset_name] = summary
        return summary


class InMemoryDatasetSnapshotRepository:
    def __init__(self, snapshots: list[DatasetSnapshot]) -> None:
        self.snapshots = snapshots

    def list_recent(self, limit):
        return self.snapshots[:limit]


class RecordingDatasetAnalysisDispatcher:
    def __init__(self) -> None:
        self.dispatched: list[str] = []

    def dispatch(self, dataset_name):
        self.dispatched.append(dataset_name)


PROPORTIONS = {"training": 0.6, "validation": 0.2, "calibration": 0.1, "test": 0.1}


def _client(datasets, summaries, *, max_rows=1000) -> TestClient:
    snapshot = DatasetSnapshot(
        snapshot_id="snap",
        specification={},
        period_start=date(2026, 9, 1),
        period_end=date(2026, 9, 30),
        maturing_days=4,
        strata_counts={},
        partition_counts={},
        schema_versions=(1,),
        content_hash="h" * 64,
        trigger="manual",
        dataset_refs={"all": "mature-sample-snap", "final": "mature-sample-snap-final"},
        created_at=datetime(2026, 10, 1, tzinfo=UTC),
    )
    app = FastAPI()
    _register_error_handlers(app)
    app.include_router(router)
    app.dependency_overrides[get_prepare_dataset_split_use_case] = lambda: (
        PrepareDatasetSplitUseCase(
            datasets,
            summaries,
            snapshots=InMemoryDatasetSnapshotRepository([snapshot]),
            max_rows=max_rows,
        )
    )
    app.dependency_overrides[get_append_dataset_rows_use_case] = lambda: (
        AppendDatasetRowsUseCase(datasets, summaries, RecordingDatasetAnalysisDispatcher())
    )
    return TestClient(app)


def _rows(count: int) -> list[dict]:
    return [{"id": str(i), "channel": "web" if i % 2 else "app"} for i in range(count)]


def test_split_preview_and_create_return_distribution_and_source_context():
    datasets = InMemoryDatasetRepository({"source": _rows(40)})
    client = _client(datasets, InMemoryDatasetSummaryRepository())
    body = {"proportions": PROPORTIONS, "seed": 3, "stratify_fields": ["channel"]}

    preview = client.post("/datasets/source/splits/preview", json=body)
    created = client.post(
        "/datasets/source/splits", json={**body, "target_name": "source_split"}
    )

    assert preview.status_code == 200
    assert set(preview.json()["strata_distribution"]) == {"web", "app"}
    assert preview.json()["source_context"]["kind"] == "uploaded"
    assert preview.json()["warnings"] == []
    assert created.status_code == 201
    assert created.json()["strata_distribution"] == preview.json()["strata_distribution"]


def test_split_api_rejects_final_partition_row_limit_and_appends():
    datasets = InMemoryDatasetRepository(
        {"mature-sample-snap-final": _rows(20), "large": _rows(30), "source": _rows(20)}
    )
    summaries = InMemoryDatasetSummaryRepository()
    client = _client(datasets, summaries, max_rows=25)
    body = {"proportions": PROPORTIONS, "seed": 1}

    final = client.post("/datasets/mature-sample-snap-final/splits/preview", json=body)
    large = client.post("/datasets/large/splits/preview", json=body)
    client.post("/datasets/source/splits", json={**body, "target_name": "frozen"})
    append = client.post("/datasets/frozen/rows", json={"rows": [{"id": "x"}]})

    assert final.status_code == 422
    assert "reservada" in final.json()["detail"]
    assert large.status_code == 422
    assert "máximo" in large.json()["detail"]
    assert append.status_code == 409
    assert len(datasets.rows["frozen"]) == 20
