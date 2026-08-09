from __future__ import annotations

import uuid

import pytest

from src.application.dtos.pre_process_dtos import PreProcessAlertInput
from src.application.ports.aric_alert_port import AricAlertPort, AricAlertSignals
from src.application.ports.host_service_customer_port import (
    HostCustomerProfile,
    HostServiceCustomerProfilePort,
)
from src.application.ports.host_service_personal_data_changes_port import (
    HostServicePersonalDataChangesPort,
)
from src.application.ports.host_service_transaction_history_port import (
    HostServiceTransactionHistoryPort,
)
from src.application.use_cases.alerts.pre_process_alert import (
    PreProcessAlertUseCase,
)
from src.domain.alerts.exceptions import MandatoryAlertDataMissingError

VALID_PAYLOAD = {
    "eventId": "evt-1",
    "eventType": "paymentRT",
    "eventTime": "2026-08-09T10:00:00Z",
    "customerId": "10264559",
    "accountId": "acct-1",
    "channel": "mobileApp",
    "merchantId": "merch-1",
    "merchantName": "Acme",
    "integrationPoint": "IP-1",
    "serviceDescription": "desc",
    "msgStatus": "APPROVED",
    "direction": "OUT",
    "msgReason": "none",
    "customerClientCode": "CC-1",
    "object": {
        "triggeredRules": [{"name": "rule1"}],
        "tags": [{"values": ["tag1"]}],
        "triggeredModels": ["model1"],
    },
    "biocatch": {
        "score": 10,
        "ip": "1.2.3.4",
        "muid": "muid-1",
        "customerSessionID": "sess-1",
    },
    "entryMode": {"terminalDataInputModeCapability": "manual"},
    "session": {"sessionId": "sess-1"},
    "counterpartyName": {"fullName": "John Doe"},
    "amount": {"baseValue": 100.0},
    "device": {"ipAddress": "5.6.7.8", "userAgentString": "UA"},
    "_metadata": {"searchable": {"deviceId": "dev-1"}},
    "personalId": "pid-1",
}


class RecordingAricAlertPort(AricAlertPort):
    def __init__(self) -> None:
        self.calls = 0

    def fetch_signals(self, event_id, session_id) -> AricAlertSignals:
        self.calls += 1
        return AricAlertSignals(is_rat=False, is_bot=False)


class RecordingHostServiceCustomerProfilePort(HostServiceCustomerProfilePort):
    def __init__(self) -> None:
        self.calls = 0

    def fetch_customer_profile(self, customer_id) -> HostCustomerProfile:
        self.calls += 1
        return HostCustomerProfile(customer_name="Jane")


class RecordingHostServiceTransactionHistoryPort(
    HostServiceTransactionHistoryPort
):
    def __init__(self) -> None:
        self.calls = 0

    def fetch_transaction_history(self, customer_id, account_id):
        self.calls += 1
        return []


class FlakyHostServicePersonalDataChangesPort(
    HostServicePersonalDataChangesPort
):
    def __init__(self, fail_times: int) -> None:
        self.fail_times = fail_times
        self.calls = 0

    def fetch_personal_data_changes(self, customer_id):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError("host service temporarily unavailable")
        return []


def _use_case(personal_data_port=None) -> PreProcessAlertUseCase:
    return PreProcessAlertUseCase(
        aric_alert_port=RecordingAricAlertPort(),
        host_customer_profile_port=RecordingHostServiceCustomerProfilePort(),
        host_transaction_history_port=(
            RecordingHostServiceTransactionHistoryPort()
        ),
        host_personal_data_changes_port=(
            personal_data_port or FlakyHostServicePersonalDataChangesPort(0)
        ),
    )


def test_pre_process_alert_extracts_fields_and_enriches() -> None:
    use_case = _use_case()

    output = use_case.execute(
        PreProcessAlertInput(alert_id=uuid.uuid4(), payload=VALID_PAYLOAD)
    )

    assert output.mandatory_fields["customer_id"] == "10264559"
    assert output.mandatory_fields["amount"] == 100.0
    assert "card_bin" not in output.mandatory_fields
    assert output.optional_fields["reason_code"] == "none"
    assert output.enrichment["customer_profile"].customer_name == "Jane"
    assert "pre_process" in output.pre_process_note.lower()


def test_pre_process_alert_raises_on_missing_mandatory_field() -> None:
    payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "customerId"}
    use_case = _use_case()

    with pytest.raises(MandatoryAlertDataMissingError) as exc_info:
        use_case.execute(
            PreProcessAlertInput(alert_id=uuid.uuid4(), payload=payload)
        )

    assert "customer_id" in exc_info.value.missing_fields


def test_pre_process_alert_retries_transient_fetch_failures() -> None:
    flaky = FlakyHostServicePersonalDataChangesPort(fail_times=2)
    use_case = _use_case(personal_data_port=flaky)

    output = use_case.execute(
        PreProcessAlertInput(alert_id=uuid.uuid4(), payload=VALID_PAYLOAD)
    )

    assert flaky.calls == 3
    assert output.enrichment["personal_data_changes"] == []


def test_pre_process_alert_gives_up_after_max_attempts() -> None:
    always_fails = FlakyHostServicePersonalDataChangesPort(fail_times=99)
    use_case = _use_case(personal_data_port=always_fails)

    with pytest.raises(RuntimeError):
        use_case.execute(
            PreProcessAlertInput(alert_id=uuid.uuid4(), payload=VALID_PAYLOAD)
        )

    assert always_fails.calls == 3
