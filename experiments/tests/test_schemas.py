import json

from schemas import AlertInput


def _minimal(**overrides):
    data = {
        "customerid": "8614703",
        "eventtype": "paymentRT",
        "channel": "GL",
        "integrationpoint": "SMGG20210247 - postIdentityDocumentTransfers",
        "amount_value": 3000000.0,
        "fecha_transaccion": "2026-07-10 11:32:46.000",
    }
    data.update(overrides)
    return data


def test_from_dict_ignores_unknown_fields():
    alert = AlertInput.from_dict(_minimal(campo_inventado="algo"))
    assert alert.customerid == "8614703"
    assert not hasattr(alert, "campo_inventado")


def test_from_dict_coerces_customerid_from_float_like_string():
    alert = AlertInput.from_dict(_minimal(customerid="8614703.0"))
    assert alert.customerid == "8614703"


def test_from_dict_invalid_numeric_field_defaults_to_zero_not_exception():
    alert = AlertInput.from_dict(_minimal(amount_value="no-es-un-numero"))
    assert alert.amount_value == 0.0


def test_from_dict_invalid_int_flag_defaults_to_zero():
    alert = AlertInput.from_dict(_minimal(biocatch_isRat="N/A"))
    assert alert.biocatch_isRat == 0


def test_is_cold_start_true_when_no_fecha_alta():
    alert = AlertInput.from_dict(_minimal(transacciones_json="[]"))
    assert alert.is_cold_start() is True


def test_is_cold_start_false_with_history_and_fecha_alta():
    historial = json.dumps([{"monto": 1000, "canal": "GL"}])
    alert = AlertInput.from_dict(_minimal(fecha_alta="2020-01-01", transacciones_json=historial))
    assert alert.is_cold_start() is False


def test_get_recent_transactions_parses_json_list():
    historial = json.dumps([{"monto": 1000}, {"monto": 2000}])
    alert = AlertInput.from_dict(_minimal(transacciones_json=historial))
    txs = alert.get_recent_transactions()
    assert len(txs) == 2
    assert txs[0]["monto"] == 1000


def test_get_recent_transactions_malformed_json_returns_empty_list():
    alert = AlertInput.from_dict(_minimal(transacciones_json="{esto no es json valido"))
    assert alert.get_recent_transactions() == []


def test_to_dict_replaces_raw_transacciones_json_with_parsed_list():
    historial = json.dumps([{"monto": 1000}])
    alert = AlertInput.from_dict(_minimal(transacciones_json=historial))
    result = alert.to_dict()
    assert isinstance(result["transacciones_json"], list)
    assert result["transacciones_json"][0]["monto"] == 1000
