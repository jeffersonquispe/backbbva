from __future__ import annotations

import uuid

from src.application.dtos.pre_process_dtos import PreProcessAlertOutput
from src.application.dtos.profile_alert_dtos import ProfileAlertInput
from src.application.ports.aric_alert_port import AricAlertSignals
from src.application.ports.host_service_customer_port import HostCustomerProfile
from src.application.ports.host_service_personal_data_changes_port import (
    PersonalDataChangeEntry,
)
from src.application.ports.host_service_transaction_history_port import (
    TransactionHistoryEntry,
)
from src.application.use_cases.alerts.profile_alert_deterministic import (
    DeterministicProfileAlertUseCase,
)


def _pre_process(
    *,
    mandatory: dict | None = None,
    customer_profile: HostCustomerProfile | None = None,
    personal_data_changes: list[PersonalDataChangeEntry] | None = None,
    aric_signals: AricAlertSignals | None = None,
    transaction_history: list[TransactionHistoryEntry] | None = None,
) -> PreProcessAlertOutput:
    return PreProcessAlertOutput(
        mandatory_fields=mandatory
        or {
            "customer_id": "cust-1",
            "amount": "63800.00",
            "channel": "APP",
            "integration_point": "00 - Compra",
            "merchant_name": "Acme",
            "rules": "RULE-1",
            "device_id": "dev-1",
            "ip_channel": "1.2.3.4",
            "user_agent": "UA",
            "counterparty": "Jane Doe",
        },
        optional_fields={},
        enrichment={
            "customer_profile": customer_profile
            or HostCustomerProfile(
                customer_name="John Smith",
                document_number="CC-123",
                address="123 Main St",
            ),
            "personal_data_changes": (
                personal_data_changes if personal_data_changes is not None else []
            ),
            "aric_signals": aric_signals or AricAlertSignals(),
            "transaction_history": (
                transaction_history if transaction_history is not None else []
            ),
        },
        pre_process_note="note",
    )


def _use_case() -> DeterministicProfileAlertUseCase:
    return DeterministicProfileAlertUseCase()


def test_user_profile_includes_identity_changes_and_device_info() -> None:
    output = _use_case().execute(
        ProfileAlertInput(
            alert_id=uuid.uuid4(),
            pre_process=_pre_process(
                personal_data_changes=[
                    PersonalDataChangeEntry(
                        changed_field="mobile_number",
                        changed_at="2026-01-01",
                    )
                ],
            ),
        )
    )

    assert "John Smith" in output.user_profile
    assert "CC-123" in output.user_profile
    assert "mobile_number" in output.user_profile
    assert "dev-1" in output.user_profile
    assert "1.2.3.4" in output.user_profile


def test_user_profile_reports_no_changes_when_none_on_record() -> None:
    output = _use_case().execute(
        ProfileAlertInput(alert_id=uuid.uuid4(), pre_process=_pre_process())
    )

    assert "No hay cambios de datos personales registrados." in output.user_profile


def test_transaction_profile_lists_biocatch_flags() -> None:
    output = _use_case().execute(
        ProfileAlertInput(
            alert_id=uuid.uuid4(),
            pre_process=_pre_process(
                aric_signals=AricAlertSignals(is_rat=True, is_bot=True),
            ),
        )
    )

    assert "RAT" in output.transaction_profile
    assert "bot" in output.transaction_profile
    assert "RULE-1" in output.transaction_profile


def test_transaction_profile_lists_new_biocatch_flags_and_scores() -> None:
    output = _use_case().execute(
        ProfileAlertInput(
            alert_id=uuid.uuid4(),
            pre_process=_pre_process(
                mandatory={
                    "customer_id": "cust-1",
                    "channel": "GL",
                    "biocatch_score": 258.0,
                    "model_score": 0.27087,
                },
                aric_signals=AricAlertSignals(
                    ind_robo1=True,
                    is_on_call_active=True,
                    is_voip_on_call=True,
                    screen_broadcast=True,
                ),
            ),
        )
    )

    assert "BioCatch: 258.0" in output.transaction_profile
    assert "modelo: 0.27087" in output.transaction_profile
    assert "indicador de robo" in output.transaction_profile
    assert "llamada VoIP activa" in output.transaction_profile
    assert "transmisión de pantalla" in output.transaction_profile


def test_transaction_profile_reports_no_flags_when_clean() -> None:
    output = _use_case().execute(
        ProfileAlertInput(alert_id=uuid.uuid4(), pre_process=_pre_process())
    )

    assert (
        "No se detectaron señales anómalas de dispositivo o sesión en "
        "BioCatch." in output.transaction_profile
    )


def test_transaction_profile_destination_check_is_deterministic() -> None:
    use_case = _use_case()
    pre_process = _pre_process()

    first = use_case.execute(
        ProfileAlertInput(alert_id=uuid.uuid4(), pre_process=pre_process)
    )
    second = use_case.execute(
        ProfileAlertInput(alert_id=uuid.uuid4(), pre_process=pre_process)
    )

    assert first.transaction_profile == second.transaction_profile
    assert "señal simulada" in first.transaction_profile


def test_transaction_profile_skips_destination_check_without_counterparty() -> None:
    mandatory = {
        "customer_id": "cust-1",
        "amount": "100",
        "channel": "APP",
    }
    output = _use_case().execute(
        ProfileAlertInput(
            alert_id=uuid.uuid4(),
            pre_process=_pre_process(mandatory=mandatory),
        )
    )

    assert "No había destino/contraparte disponible para evaluar." in (
        output.transaction_profile
    )


def test_transactional_profile_reports_no_history() -> None:
    output = _use_case().execute(
        ProfileAlertInput(alert_id=uuid.uuid4(), pre_process=_pre_process())
    )

    assert output.transactional_profile == (
        "No hay historial de transacciones disponible para este cliente."
    )


def test_transactional_profile_includes_exported_historical_maxima() -> None:
    output = _use_case().execute(
        ProfileAlertInput(
            alert_id=uuid.uuid4(),
            pre_process=_pre_process(
                mandatory={
                    "customer_id": "cust-1",
                    "channel": "GL",
                    "max_amount_breb": 122000.0,
                    "max_amount_card_withdrawals": 500000.0,
                }
            ),
        )
    )

    assert "Bre-B: 122,000" in output.transactional_profile
    assert "retiros con tarjeta: 500,000" in output.transactional_profile


def test_transactional_profile_computes_real_stats_over_full_history() -> None:
    history = [
        TransactionHistoryEntry(
            event_id=f"tx-{i}",
            event_type="cardNRT",
            event_time=f"2026-05-{i:02d} 10:00:00",
            amount=amount,
        )
        for i, amount in enumerate([10_000, 20_000, 30_000], start=1)
    ]
    output = _use_case().execute(
        ProfileAlertInput(
            alert_id=uuid.uuid4(),
            pre_process=_pre_process(
                mandatory={
                    "customer_id": "cust-1",
                    "amount": "500000",
                    "channel": "APP",
                },
                transaction_history=history,
            ),
        )
    )

    assert "3 transacción(es) registrada(s)" in output.transactional_profile
    assert "10,000" in output.transactional_profile
    assert "30,000" in output.transactional_profile
    assert "supera el monto más alto registrado" in output.transactional_profile
