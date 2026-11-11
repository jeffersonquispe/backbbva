from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.ports.fraud_history_archive_port import (
    ArchivedAlert,
    ArchivedAlertSummary,
    ArchiveVerificationError,
)
from src.application.ports.legal_hold_port import LegalHold
from src.application.ports.local_auth_port import LocalRole, LocalUser
from src.application.use_cases.fraud_review.get_archived_alert import (
    ArchivedAlertNotFoundError,
    GetArchivedAlertOutput,
)
from src.application.use_cases.fraud_review.manage_legal_hold import (
    LegalHoldAlertNotFoundError,
    LegalHoldAlreadyActiveError,
    LegalHoldNotActiveError,
    LegalHoldNotFoundError,
    LegalHoldReasonError,
)
from src.application.use_cases.fraud_review.search_archived_alerts import (
    ArchivedAlertHit,
    ArchiveSearchCriteriaError,
)
from src.infrastructure.entrypoint.api.factories import fraud_archive_factory as factory
from src.infrastructure.entrypoint.api.routers import fraud_archive_router
from src.infrastructure.entrypoint.api.routers.auth_router import get_current_user

NOW = datetime(2026, 11, 4, tzinfo=UTC)
HOLD = LegalHold("a1", "Requerimiento judicial 123", "CASO-1", "u", NOW)


class RecordingUseCase:
    def __init__(self, result=None, error: Exception | None = None) -> None:
        self.result, self.error, self.calls = result, error, []

    def execute(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.error:
            raise self.error
        return self.result


def _provider(use_case: RecordingUseCase):
    # A closure, not a default argument: FastAPI would copy a default value.
    def provide() -> RecordingUseCase:
        return use_case

    return provide


def _client(role: LocalRole, **use_cases: RecordingUseCase) -> TestClient:
    user = LocalUser(
        id=UUID("00000000-0000-0000-0000-000000000001"),
        email="u@example.com",
        name="U",
        password_hash="",
        role=role,
        is_active=True,
        created_at=NOW,
        updated_at=NOW,
    )
    app = FastAPI()
    app.include_router(fraud_archive_router.router)
    app.dependency_overrides[get_current_user] = lambda: user
    mapping = {
        "get": factory.get_get_archived_alert_use_case,
        "place": factory.get_place_legal_hold_use_case,
        "release": factory.get_release_legal_hold_use_case,
        "list": factory.get_list_legal_holds_use_case,
        "search": factory.get_search_archived_alerts_use_case,
        "hold": factory.get_get_legal_hold_use_case,
    }
    for name, use_case in use_cases.items():
        # The router imported these names, so override where it looks them up.
        app.dependency_overrides[
            getattr(fraud_archive_router, mapping[name].__name__)
        ] = _provider(use_case)
    return TestClient(app)


ARCHIVED = ArchivedAlert(
    "a1",
    date(2025, 10, 26),
    "fraud-history-archive/x.jsonl.gz",
    {"alert_id": "a1", "amount": "10.50"},
    [{"note": "n"}],
    "record",
)


def test_manager_and_reviewer_read_an_archived_alert() -> None:
    for role in (LocalRole.MANAGER, LocalRole.FRAUD_REVIEWER):
        use_case = RecordingUseCase(GetArchivedAlertOutput(ARCHIVED))

        response = _client(role, get=use_case).get("/fraud-history/archive/a1")

        assert response.status_code == 200
        assert response.json() == {
            "alert_id": "a1",
            "created_day": "2025-10-26",
            "archive_object": "fraud-history-archive/x.jsonl.gz",
            "verified_against": "record",
            "alert": {"alert_id": "a1", "amount": "10.50"},
            "fraud_label_reviews": [{"note": "n"}],
        }
        assert use_case.calls == [
            (("a1",), {"requested_by": "00000000-0000-0000-0000-000000000001"})
        ]


def test_other_roles_cannot_read_the_archive_or_touch_holds() -> None:
    for role in (
        LocalRole.FRAUD_ANALYST,
        LocalRole.CHANNEL_MANAGER,
        LocalRole.RELEASE_MANAGER,
    ):
        client = _client(role)
        assert client.get("/fraud-history/archive/a1").status_code == 403
        assert client.get("/fraud-history/legal-holds").status_code == 403
        body = {"reason": "Requerimiento judicial 123"}
        assert client.put("/fraud-history/legal-holds/a1", json=body).status_code == 403
        assert (
            client.post("/fraud-history/legal-holds/a1/release", json=body).status_code
            == 403
        )


def test_a_reviewer_can_read_but_not_operate_holds() -> None:
    client = _client(LocalRole.FRAUD_REVIEWER)

    assert client.get("/fraud-history/legal-holds").status_code == 403
    assert (
        client.put(
            "/fraud-history/legal-holds/a1",
            json={"reason": "Requerimiento judicial 123"},
        ).status_code
        == 403
    )


def test_unknown_alert_is_404_and_a_corrupt_archive_is_never_served() -> None:
    missing = _client(
        LocalRole.MANAGER, get=RecordingUseCase(error=ArchivedAlertNotFoundError("a1"))
    )
    corrupt = _client(
        LocalRole.MANAGER, get=RecordingUseCase(error=ArchiveVerificationError("x"))
    )

    assert missing.get("/fraud-history/archive/a1").status_code == 404
    response = corrupt.get("/fraud-history/archive/a1")
    assert response.status_code == 502
    assert response.json()["detail"] == {"code": "ARCHIVE_INTEGRITY_FAILED"}


def test_manager_places_a_hold_recording_who_placed_it() -> None:
    place = RecordingUseCase(HOLD)

    response = _client(LocalRole.MANAGER, place=place).put(
        "/fraud-history/legal-holds/a1",
        json={"reason": "Requerimiento judicial 123", "case_reference": "CASO-1"},
    )

    assert response.status_code == 201
    assert (
        response.json()["active"] is True
        and response.json()["case_reference"] == "CASO-1"
    )
    assert place.calls == [
        (
            (),
            {
                "alert_id": "a1",
                "reason": "Requerimiento judicial 123",
                "case_reference": "CASO-1",
                "placed_by": "00000000-0000-0000-0000-000000000001",
            },
        )
    ]


def test_place_hold_errors_map_to_safe_codes() -> None:
    body = {"reason": "Requerimiento judicial 123"}
    cases = [
        (LegalHoldAlertNotFoundError("a1"), 404, "ALERT_NOT_FOUND"),
        (LegalHoldAlreadyActiveError("a1"), 409, "LEGAL_HOLD_ALREADY_ACTIVE"),
        (LegalHoldReasonError("reason too short"), 422, "LEGAL_HOLD_REASON"),
    ]
    for error, status, code in cases:
        response = _client(LocalRole.MANAGER, place=RecordingUseCase(error=error)).put(
            "/fraud-history/legal-holds/a1", json=body
        )
        assert response.status_code == status
        assert response.json()["detail"]["code"] == code
    # An empty reason never reaches the use case.
    assert (
        _client(LocalRole.MANAGER, place=RecordingUseCase(HOLD))
        .put("/fraud-history/legal-holds/a1", json={"reason": ""})
        .status_code
        == 422
    )


def test_release_and_list() -> None:
    released = LegalHold(
        "a1", "r", None, "u", NOW, NOW, "u2", "Oficio de levantamiento"
    )
    release = RecordingUseCase(released)
    listing = RecordingUseCase([HOLD])
    client = _client(LocalRole.MANAGER, release=release, list=listing)

    response = client.post(
        "/fraud-history/legal-holds/a1/release",
        json={"reason": "Oficio de levantamiento"},
    )
    assert response.status_code == 200
    assert response.json()["active"] is False and response.json()["released_by"] == "u2"

    assert [
        h["alert_id"] for h in client.get("/fraud-history/legal-holds?limit=5").json()
    ] == ["a1"]
    assert listing.calls == [((), {"limit": 5})]

    missing = _client(
        LocalRole.MANAGER, release=RecordingUseCase(error=LegalHoldNotActiveError("a1"))
    ).post(
        "/fraud-history/legal-holds/a1/release",
        json={"reason": "Oficio de levantamiento"},
    )
    assert missing.status_code == 404


def test_search_returns_hits_with_the_hold_flag_and_passes_one_criterion() -> None:
    hit = ArchivedAlertHit(ArchivedAlertSummary("a1", "EV-1", date(2025, 10, 26)), True)
    search = RecordingUseCase([hit])

    response = _client(LocalRole.FRAUD_REVIEWER, search=search).get(
        "/fraud-history/archive?event_id=EV-1&limit=5"
    )

    assert response.status_code == 200
    assert response.json() == [
        {"alert_id": "a1", "event_id": "EV-1", "created_day": "2025-10-26", "legal_hold": True}
    ]
    assert search.calls == [
        (
            (),
            {
                "requested_by": "00000000-0000-0000-0000-000000000001",
                "alert_id": None,
                "event_id": "EV-1",
                "day": None,
                "limit": 5,
            },
        )
    ]


def test_search_rejects_bad_criteria_and_unauthorized_roles() -> None:
    bad = _client(LocalRole.MANAGER, search=RecordingUseCase(error=ArchiveSearchCriteriaError("x")))
    assert bad.get("/fraud-history/archive").status_code == 422
    assert bad.get("/fraud-history/archive?day=not-a-date").status_code == 422
    assert _client(LocalRole.RELEASE_MANAGER).get("/fraud-history/archive?alert_id=a1").status_code == 403


def test_one_hold_can_be_read_by_archive_readers() -> None:
    now = datetime(2026, 11, 4, tzinfo=UTC)
    found = _client(
        LocalRole.FRAUD_REVIEWER, hold=RecordingUseCase(LegalHold("a1", "r" * 12, None, "u", now))
    ).get("/fraud-history/legal-holds/a1")
    missing = _client(
        LocalRole.MANAGER, hold=RecordingUseCase(error=LegalHoldNotFoundError("a1"))
    ).get("/fraud-history/legal-holds/a1")

    assert found.status_code == 200 and found.json()["active"] is True
    assert missing.status_code == 404
