from __future__ import annotations

import random

import httpx
import pytest

from src.application.ports.alert_dispatch_gateway_port import AlertDispatchResult
from src.infrastructure.platform_gateway.http.http_alert_dispatch_gateway import (
    HttpAlertDispatchGateway,
)
from src.infrastructure.platform_gateway.http.http_dataset_reader_gateway import (
    HttpDatasetReaderGateway,
)
from src.infrastructure.platform_gateway.http.http_event_sink import HttpEventSink


def _client(handler) -> httpx.Client:
    transport = httpx.MockTransport(handler)
    return httpx.Client(transport=transport, base_url="http://aria-api.test")


def test_dispatch_returns_result_and_sends_expected_body_and_auth_header():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            202,
            json={
                "alert_id": "a1",
                "async_operation_id": "op1",
                "workflow_execution_id": "wf1",
                "status": "queued",
            },
        )

    gateway = HttpAlertDispatchGateway(
        base_url="http://aria-api.test", token="secret", client=_client(handler)
    )

    result = gateway.dispatch({"amount": 10}, created_by="simulator")

    assert result == AlertDispatchResult(
        alert_id="a1",
        async_operation_id="op1",
        workflow_execution_id="wf1",
        status="queued",
    )
    assert len(requests) == 1
    assert requests[0].url.path == "/alerts/test"
    assert requests[0].headers["authorization"] == "Bearer secret"
    import json

    assert json.loads(requests[0].content) == {
        "event": {"amount": 10},
        "created_by": "simulator",
        # Simulator traffic stops while the agent is switched off.
        "origin": "simulator",
    }


def test_dispatch_omits_auth_header_when_no_token():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "authorization" not in request.headers
        return httpx.Response(
            202,
            json={
                "alert_id": "a1",
                "async_operation_id": "op1",
                "workflow_execution_id": "wf1",
                "status": "queued",
            },
        )

    gateway = HttpAlertDispatchGateway(
        base_url="http://aria-api.test", client=_client(handler)
    )

    gateway.dispatch({"amount": 10})


def test_dispatch_raises_runtime_error_with_status_and_body_on_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="bad payload")

    gateway = HttpAlertDispatchGateway(
        base_url="http://aria-api.test", client=_client(handler)
    )

    with pytest.raises(RuntimeError) as exc_info:
        gateway.dispatch({"amount": 10})

    assert "400" in str(exc_info.value)
    assert "bad payload" in str(exc_info.value)


def test_write_batch_returns_zero_without_any_request_on_empty_rows():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no HTTP call expected for an empty batch")

    sink = HttpEventSink(base_url="http://aria-api.test", client=_client(handler))

    assert sink.write_batch("some_dataset", []) == 0


def test_write_batch_happy_path_sends_expected_body():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            202, json={"name": "ds", "total_rows": 3, "status": "processing"}
        )

    sink = HttpEventSink(base_url="http://aria-api.test", client=_client(handler))

    total = sink.write_batch("ds", [{"a": 1}, {"a": 2}])

    assert total == 3
    assert len(requests) == 1
    assert requests[0].url.path == "/datasets/ds/rows"
    import json

    assert json.loads(requests[0].content) == {"rows": [{"a": 1}, {"a": 2}]}


def test_write_batch_creates_dataset_and_retries_when_first_append_404s():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if (
            request.url.path == "/datasets/new_ds/rows"
            and len([c for c in calls if c[1] == "/datasets/new_ds/rows"]) == 1
        ):
            return httpx.Response(404, text="dataset not found")
        if request.url.path == "/datasets/empty":
            return httpx.Response(201, json={"name": "new_ds", "status": "ready"})
        return httpx.Response(
            202, json={"name": "new_ds", "total_rows": 1, "status": "processing"}
        )

    sink = HttpEventSink(base_url="http://aria-api.test", client=_client(handler))

    total = sink.write_batch("new_ds", [{"a": 1}])

    assert total == 1
    assert calls == [
        ("POST", "/datasets/new_ds/rows"),
        ("POST", "/datasets/empty"),
        ("POST", "/datasets/new_ds/rows"),
    ]


def test_write_batch_ignores_409_on_create_race_and_retries():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if (
            request.url.path == "/datasets/race_ds/rows"
            and len([c for c in calls if c[1] == "/datasets/race_ds/rows"]) == 1
        ):
            return httpx.Response(404, text="dataset not found")
        if request.url.path == "/datasets/empty":
            return httpx.Response(409, text="already exists")
        return httpx.Response(
            202, json={"name": "race_ds", "total_rows": 5, "status": "processing"}
        )

    sink = HttpEventSink(base_url="http://aria-api.test", client=_client(handler))

    total = sink.write_batch("race_ds", [{"a": 1}])

    assert total == 5


def test_write_batch_raises_runtime_error_on_other_failures():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="server exploded")

    sink = HttpEventSink(base_url="http://aria-api.test", client=_client(handler))

    with pytest.raises(RuntimeError) as exc_info:
        sink.write_batch("ds", [{"a": 1}])

    assert "500" in str(exc_info.value)
    assert "server exploded" in str(exc_info.value)


def test_sample_row_returns_none_on_404():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    gateway = HttpDatasetReaderGateway(
        base_url="http://aria-api.test", client=_client(handler)
    )

    assert gateway.sample_row("missing", random.Random(0)) is None


def test_sample_row_returns_none_when_total_is_zero():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"rows": [], "total": 0})

    gateway = HttpDatasetReaderGateway(
        base_url="http://aria-api.test", client=_client(handler)
    )

    assert gateway.sample_row("empty_ds", random.Random(0)) is None


def test_sample_row_picks_from_returned_window_when_total_fits():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={"rows": [{"a": 1}, {"a": 2}, {"a": 3}], "total": 3},
        )

    gateway = HttpDatasetReaderGateway(
        base_url="http://aria-api.test", client=_client(handler)
    )

    row = gateway.sample_row("small_ds", random.Random(0))

    assert row in [{"a": 1}, {"a": 2}, {"a": 3}]
    assert len(requests) == 1
    assert requests[0].url.params["offset"] == "0"
    assert requests[0].url.params["limit"] == "500"


def test_sample_row_issues_second_request_when_total_exceeds_window():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                200, json={"rows": [{"a": i} for i in range(500)], "total": 900}
            )
        assert request.url.params["limit"] == "1"
        return httpx.Response(200, json={"rows": [{"a": 999}], "total": 900})

    gateway = HttpDatasetReaderGateway(
        base_url="http://aria-api.test", client=_client(handler)
    )

    row = gateway.sample_row("big_ds", random.Random(0))

    assert row == {"a": 999}
    assert len(requests) == 2


def test_sample_row_second_request_empty_rows_returns_none():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                200, json={"rows": [{"a": i} for i in range(500)], "total": 900}
            )
        return httpx.Response(200, json={"rows": [], "total": 900})

    gateway = HttpDatasetReaderGateway(
        base_url="http://aria-api.test", client=_client(handler)
    )

    assert gateway.sample_row("shrunk_ds", random.Random(0)) is None
