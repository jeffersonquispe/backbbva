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
    assert output.optional_fields["amount"] == 100.0
    assert "card_bin" not in output.mandatory_fields
    assert output.optional_fields["reason_code"] == "none"
    assert output.enrichment["customer_profile"].customer_name == "Jane"
    assert "pre_process" in output.pre_process_note.lower()


# Real column names from Muestra_total_ARIA.csv - the reference dataset.
# Not the CSV's raw string values (those come through as strings via
# csv.DictReader in production), typed here since this test targets the
# use case directly.
MUESTRA_TOTAL_ARIA_PAYLOAD = {
    "eventid": "evt-flat-1",
    "eventtype": "paymentRT",
    "channel": "APP",
    "integrationpoint": "SMGG20211063 - patchPaymentRequest",
    "biocatch_score": 891,
    "amount_value": 2800000.0,
    "fecha_transaccion": "2026-05-02 23:10:13.000",
    "triggered_rules": "[CUSTOMER - Score1000Net]",
    "customerid": "8867889",
    "deviceid": "dev-flat-1",
    "device_ipaddress_encrypted": "TSICWU0L7y8F2LIpumCIrg==",
    "counterpartyentityid_encrypted": "4ZXou5GG_r9p57SQJREAdg==",
    "numero_documento": "1000003114",
    # Ground truth - never read as mandatory input, must not block or
    # leak into pre_process's extraction.
    "marcacion_final": "no-risk",
    "razon_marcacion": "[NF___ANLISIS]",
    "tipo": "NoFraude",
}


NEW_ALERT_EXPORT_PAYLOAD = {
    **MUESTRA_TOTAL_ARIA_PAYLOAD,
    "reviewstatus_first": "risk-suspected",
    "marcacion_final": "risk-suspected",
    "razon_marcacion": "[FR___NO_HABITO_TRXS]",
    "Model_score": 0.27087,
    "fecha_primer_marcacion": "2026-05-02 14:50:53.213",
    "fecha_ultima_marcacion": "2026-05-02 14:57:54.499",
    "biocatch_isMobileRat": "False",
    "biocatch_isEmulator": False,
    "biocatch_isRat": 0,
    "biocatch_isBot": "false",
    "biocatch_indrobo1": "True",
    "biocatch_isOnCall": 1,
    "biocatch_isVoipOnCall": "true",
    "biocatch_screenBroadcast": True,
    "transactionid": "1022284400130126000200452051122000",
    "output_tags": "[PARTY - outcome: deny]",
    "MontoMasAltoPSE": 360000.0,
    "MontoMasAltoBreB": 122000.0,
    "MontoMasAltoGlomo": 122000.0,
    "MontoMasAltoRetirosTarjeta": 500000.0,
    "tipo": "Fraude",
}


def test_pre_process_alert_accepts_muestra_total_aria_flat_schema() -> None:
    use_case = _use_case()

    output = use_case.execute(
        PreProcessAlertInput(
            alert_id=uuid.uuid4(), payload=MUESTRA_TOTAL_ARIA_PAYLOAD
        )
    )

    assert output.mandatory_fields["customer_id"] == "8867889"
    assert output.optional_fields["amount"] == 2800000.0
    assert output.mandatory_fields["event_id"] == "evt-flat-1"
    assert output.mandatory_fields["event_type"] == "paymentRT"
    assert output.optional_fields["biocatch_score"] == 891
    assert output.mandatory_fields["rules"] == "[CUSTOMER - Score1000Net]"
    assert output.mandatory_fields["client_code"] == "1000003114"
    # Fields this schema simply doesn't carry (merchant, session, entry
    # mode, ...) must not block pre_process.
    assert "merchant_id" not in output.mandatory_fields
    assert "account_id" not in output.mandatory_fields


def test_pre_process_alert_maps_new_export_risk_fields_without_label_leakage() -> None:
    output = _use_case().execute(
        PreProcessAlertInput(
            alert_id=uuid.uuid4(), payload=NEW_ALERT_EXPORT_PAYLOAD
        )
    )

    assert output.optional_fields["model_score"] == 0.27087
    assert output.optional_fields["transaction_id"].endswith("1122000")
    assert output.optional_fields["max_amount_pse"] == 360000.0
    assert output.optional_fields["max_amount_breb"] == 122000.0
    assert output.optional_fields["max_amount_glomo"] == 122000.0
    assert output.optional_fields["max_amount_card_withdrawals"] == 500000.0

    signals = output.enrichment["aric_signals"]
    assert signals.is_mobile_rat is False
    assert signals.is_emulator_rat is False
    assert signals.is_rat is False
    assert signals.is_bot is False
    assert signals.ind_robo1 is True
    assert signals.is_on_call_active is True
    assert signals.is_voip_on_call is True
    assert signals.screen_broadcast is True

    exposed = output.mandatory_fields.keys() | output.optional_fields.keys()
    assert not {
        "reviewstatus_first",
        "marcacion_final",
        "razon_marcacion",
        "fecha_primer_marcacion",
        "fecha_ultima_marcacion",
        "output_tags",
        "tipo",
    } & exposed


def test_pre_process_alert_raises_on_missing_mandatory_field() -> None:
    payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "customerId"}
    use_case = _use_case()

    with pytest.raises(MandatoryAlertDataMissingError) as exc_info:
        use_case.execute(
            PreProcessAlertInput(alert_id=uuid.uuid4(), payload=payload)
        )

    assert "customer_id" in exc_info.value.missing_fields


def test_pre_process_alert_does_not_block_on_missing_biocatch_counterparty_amount() -> None:
    # biocatch_score, counterparty and amount are real-world-optional (not
    # every event carries them) - regression test for them being wrongly
    # treated as mandatory and raising MandatoryAlertDataMissingError.
    payload = {
        k: v
        for k, v in VALID_PAYLOAD.items()
        if k not in ("biocatch", "counterpartyName", "amount")
    }
    use_case = _use_case()

    output = use_case.execute(
        PreProcessAlertInput(alert_id=uuid.uuid4(), payload=payload)
    )

    assert "biocatch_score" not in output.mandatory_fields
    assert "counterparty" not in output.mandatory_fields
    assert "amount" not in output.mandatory_fields
    assert "biocatch_score" not in output.optional_fields
    assert "counterparty" not in output.optional_fields
    assert "amount" not in output.optional_fields


def test_pre_process_alert_retries_transient_fetch_failures() -> None:
    flaky = FlakyHostServicePersonalDataChangesPort(fail_times=2)
    use_case = _use_case(personal_data_port=flaky)

    output = use_case.execute(
        PreProcessAlertInput(alert_id=uuid.uuid4(), payload=VALID_PAYLOAD)
    )

    assert flaky.calls == 3
    assert output.enrichment["personal_data_changes"] == []


def test_pre_process_alert_prefers_payload_transaction_history_over_port() -> None:
    tx_port = RecordingHostServiceTransactionHistoryPort()
    use_case = PreProcessAlertUseCase(
        aric_alert_port=RecordingAricAlertPort(),
        host_customer_profile_port=RecordingHostServiceCustomerProfilePort(),
        host_transaction_history_port=tx_port,
        host_personal_data_changes_port=FlakyHostServicePersonalDataChangesPort(0),
    )
    payload = {
        **VALID_PAYLOAD,
        "transacciones_json": (
            '["{\\"tipo_transaccion\\":\\"cardNRT\\",'
            '\\"amount_value\\":63800.00,'
            '\\"integrationpoint\\":\\"00 - Compra\\",'
            '\\"eventtime\\":\\"2026-05-04 16:00:44\\"}"]'
        ),
    }

    output = use_case.execute(
        PreProcessAlertInput(alert_id=uuid.uuid4(), payload=payload)
    )

    assert tx_port.calls == 0
    history = output.enrichment["transaction_history"]
    assert len(history) == 1
    assert history[0].event_type == "cardNRT"
    assert history[0].amount == 63800.0
    assert history[0].event_time == "2026-05-04 16:00:44"


def test_pre_process_alert_preserves_new_transaction_history_details() -> None:
    tx_port = RecordingHostServiceTransactionHistoryPort()
    use_case = PreProcessAlertUseCase(
        aric_alert_port=RecordingAricAlertPort(),
        host_customer_profile_port=RecordingHostServiceCustomerProfilePort(),
        host_transaction_history_port=tx_port,
        host_personal_data_changes_port=FlakyHostServicePersonalDataChangesPort(0),
    )
    payload = {
        **VALID_PAYLOAD,
        "transacciones_json": [
            {
                "tipo_transaccion": "paymentRT",
                "amount_value": 122000.0,
                "alertas": "PARTY - dg_breb_lista_negra_cedula",
                "cuenta_origen": "account-hash",
                "integrationpoint": "paymentsCreateRequestSendTransferV0",
                "eventtime": "2026-05-02 14:47:35",
                "canal": "GL",
                "destino": "counterparty-hash",
            }
        ],
    }

    output = use_case.execute(
        PreProcessAlertInput(alert_id=uuid.uuid4(), payload=payload)
    )

    assert tx_port.calls == 0
    transaction = output.enrichment["transaction_history"][0]
    assert transaction.alerts == "PARTY - dg_breb_lista_negra_cedula"
    assert transaction.account_id == "account-hash"
    assert transaction.integration_point == "paymentsCreateRequestSendTransferV0"
    assert transaction.channel == "GL"
    assert transaction.counterparty == "counterparty-hash"


def test_pre_process_alert_falls_back_to_port_when_no_transactions_in_payload() -> None:
    tx_port = RecordingHostServiceTransactionHistoryPort()
    use_case = PreProcessAlertUseCase(
        aric_alert_port=RecordingAricAlertPort(),
        host_customer_profile_port=RecordingHostServiceCustomerProfilePort(),
        host_transaction_history_port=tx_port,
        host_personal_data_changes_port=FlakyHostServicePersonalDataChangesPort(0),
    )

    use_case.execute(
        PreProcessAlertInput(alert_id=uuid.uuid4(), payload=VALID_PAYLOAD)
    )

    assert tx_port.calls == 1


def test_pre_process_alert_gives_up_after_max_attempts() -> None:
    always_fails = FlakyHostServicePersonalDataChangesPort(fail_times=99)
    use_case = _use_case(personal_data_port=always_fails)

    with pytest.raises(RuntimeError):
        use_case.execute(
            PreProcessAlertInput(alert_id=uuid.uuid4(), payload=VALID_PAYLOAD)
        )

    assert always_fails.calls == 3
