"""Black-box local checks for the Event API HTTP contract.

Requires the Event API and OIDC issuer configured in local Compose. This
script is intentionally not run as part of unit-test commands.
"""

from __future__ import annotations

import base64
import http.client
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from uuid import uuid4

import redis

BASE_URL = os.getenv("EVENT_API_BASE_URL", "http://127.0.0.1:8001").rstrip("/")
UNAVAILABLE_URL = os.getenv(
    "EVENT_API_UNAVAILABLE_URL", "http://localhost:8003"
).rstrip("/")
TOKEN = os.getenv("EVENT_API_E2E_TOKEN", "")
OIDC_BASE_URL = os.getenv("EVENT_API_OIDC_BASE_URL", "http://127.0.0.1:8085")
MAX_BODY_BYTES = int(os.getenv("EVENT_API_MAX_BODY_BYTES", "262144"))
PRODUCTION_QUEUE = os.getenv("EVENT_API_PRODUCTION_QUEUE", "production_events")
BROKER_URL = os.getenv("EVENT_API_BROKER_URL", "redis://localhost:6379/0")
ISOLATED_QUEUES = tuple(
    filter(
        None,
        (
            os.getenv("CELERY_TEST_QUEUE", "test"),
            os.getenv("CELERY_SIMULATOR_ALERT_QUEUE", "simulator_alerts"),
        ),
    )
)


def _request(
    url: str,
    *,
    token: str | None,
    payload: bytes,
    content_type: str = "application/json",
) -> tuple[int, dict | str]:
    headers = {"Content-Type": content_type}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        response = urllib.request.urlopen(request, timeout=10)
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        try:
            return error.code, json.loads(body)
        except json.JSONDecodeError:
            return error.code, body
    with response:
        body = response.read().decode("utf-8")
        return response.status, json.loads(body)


def _event(alert_id: str, event_id: str, **summary_fields: object) -> bytes:
    return json.dumps(
        {"alert_id": alert_id, "event_id": event_id, **summary_fields}
    ).encode()


def _wait_for_event_api() -> None:
    request = urllib.request.Request(f"{BASE_URL}/health", method="GET")
    deadline = time.monotonic() + 90
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                if response.status == 200:
                    return
        except (
            urllib.error.URLError,
            http.client.HTTPException,
            OSError,
            TimeoutError,
        ) as exc:
            last_error = exc
            time.sleep(2)
    raise RuntimeError("Event API did not become ready") from last_error


def _event_is_in_queue(client: redis.Redis, queue: str, event_id: str) -> bool:
    for raw_message in client.lrange(queue, 0, -1):
        try:
            message = json.loads(raw_message)
            headers = message.get("headers", {})
            body = base64.b64decode(message.get("body", ""))
        except (TypeError, ValueError):
            continue
        if (
            headers.get("id") == event_id
            and headers.get("task") == "events.production.receive"
            and event_id.encode() in body
        ):
            return True
    return False


def _assert_event_queue_isolation(event_id: str) -> None:
    client = redis.Redis.from_url(BROKER_URL)
    try:
        assert _event_is_in_queue(client, PRODUCTION_QUEUE, event_id), (
            f"event {event_id} was not published to the {PRODUCTION_QUEUE!r} queue"
        )
        for queue in ISOLATED_QUEUES:
            assert not _event_is_in_queue(client, queue, event_id), (
                f"production event {event_id} leaked into isolated queue {queue!r}"
            )
    finally:
        client.close()


def _get_local_oidc_token() -> str:
    token_url = f"{OIDC_BASE_URL.rstrip('/')}/realms/aria/protocol/openid-connect/token"
    body = urllib.parse.urlencode(
        {
            "grant_type": "client_credentials",
            "client_id": os.getenv("EVENT_API_E2E_CLIENT_ID", "frm"),
            "client_secret": os.getenv(
                "EVENT_API_E2E_CLIENT_SECRET", "frm-local-secret"
            ),
        }
    ).encode()
    request = urllib.request.Request(
        token_url,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    deadline = time.monotonic() + 120
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                token_response = json.loads(response.read())
                return token_response["access_token"]
        except (
            urllib.error.URLError,
            http.client.HTTPException,
            OSError,
            TimeoutError,
            json.JSONDecodeError,
            KeyError,
        ) as exc:
            last_error = exc
            time.sleep(2)
    raise RuntimeError("Local OIDC issuer did not return a token") from last_error


def run() -> None:
    global TOKEN
    _wait_for_event_api()
    if not TOKEN:
        TOKEN = _get_local_oidc_token()

    event_id = f"e2e-{uuid4()}"
    alert_id = f"alert-{uuid4()}"
    payload = _event(
        alert_id,
        event_id,
        channel="card",
        risk_score=0.97,
        transaction={"amount": 125000},
    )

    status_code, _ = _request(
        f"{BASE_URL}/api/event/events", token=None, payload=payload
    )
    assert status_code == 401, f"missing-token response was {status_code}"
    status_code, _ = _request(
        f"{BASE_URL}/api/event/events", token="invalid-oidc-token", payload=payload
    )
    assert status_code == 401, f"invalid-token response was {status_code}"

    status_code, accepted = _request(
        f"{BASE_URL}/api/event/events", token=TOKEN, payload=payload
    )
    assert status_code == 202, f"event was not accepted: {status_code} {accepted}"
    assert accepted["duplicate"] is False

    status_code, conflict = _request(
        f"{BASE_URL}/api/event/events",
        token=TOKEN,
        payload=_event(f"different-alert-{uuid4()}", event_id),
    )
    assert status_code == 409, f"event id conflict was not rejected: {status_code} {conflict}"

    status_code, duplicate = _request(
        f"{BASE_URL}/api/event/events", token=TOKEN, payload=payload
    )
    assert status_code == 202 and duplicate["duplicate"] is True
    assert duplicate["receipt_id"] == accepted["receipt_id"]
    _assert_event_queue_isolation(event_id)

    status_code, _ = _request(
        f"{BASE_URL}/api/event/events",
        token=TOKEN,
        payload=b"{malformed",
    )
    assert status_code == 400, f"malformed JSON response was {status_code}"

    status_code, _ = _request(
        f"{BASE_URL}/api/event/events",
        token=TOKEN,
        payload=b" " * (MAX_BODY_BYTES + 1),
    )
    assert status_code == 413, f"oversized body response was {status_code}"

    retry_event_id = f"e2e-retry-{uuid4()}"
    retry_payload = _event(f"alert-{uuid4()}", retry_event_id)
    status_code, _ = _request(
        f"{UNAVAILABLE_URL}/api/event/events",
        token=TOKEN,
        payload=retry_payload,
    )
    assert status_code == 503, f"unavailable queue response was {status_code}"

    status_code, retry = _request(
        f"{BASE_URL}/api/event/events", token=TOKEN, payload=retry_payload
    )
    assert status_code == 202, f"event retry was not accepted: {status_code} {retry}"
    assert retry["duplicate"] is False
    _assert_event_queue_isolation(retry_event_id)
    print("Event API E2E contract passed")


if __name__ == "__main__":
    run()
