"""Create the reusable alert-schema E2E baseline through the public API.

Credentials are supplied only through E2E_* environment variables. The script
never prints tokens or passwords and never connects to a database directly.
"""

from __future__ import annotations

import csv
import json
import os
import sys
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

BASE_URL = os.getenv("E2E_BASE_URL", "http://localhost").rstrip("/")
DATASET_NAME = "Muestra_total_ARIA_JUl_head5"
FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "frontend_mockup/e2e/fixtures/muestra_total_aria_head5.csv"
)
OPENER = build_opener(ProxyHandler({}))


def _field(
    identifier: str, name: str, location: str, kind: str = "string", **extra: object
) -> dict:
    return {
        "id": identifier,
        "data_source": "aric",
        "field": name,
        "field_name": name,
        "field_ds_loc": location,
        "type": kind,
        "is_alert": True,
        "is_mandatory": True,
        "is_history": False,
        "is_core": name in {"event_id", "event_type", "channel", "amount"},
        "is_label": False,
        "is_sensible": False,
        "sensitivity_strategy": None,
        "group": "Evento",
        "description": "Campo de Muestra_total_ARIA_JUl",
        "use_locale": False,
        "locale_type": None,
        **extra,
    }


def _optional(
    identifier: str, name: str, location: str, kind: str = "string", **extra: object
) -> dict:
    return _field(identifier, name, location, kind, is_mandatory=False, **extra)


def _outcome(identifier: str, name: str, location: str) -> dict:
    return _optional(identifier, name, location, is_label=True, group="Desenlace")


FIELDS = [
    _field("event-id", "event_id", "eventid"),
    _field("event-time", "event_time", "fecha_transaccion", "datetime"),
    _field("event-type", "event_type", "eventtype"),
    _field("channel", "channel", "channel"),
    _field("entrypoint", "entrypoint", "integrationpoint"),
    _field(
        "amount",
        "amount",
        "amount_value",
        "number",
        use_locale=True,
        locale_type="es-CO",
    ),
    _field(
        "customer-id",
        "customer_id",
        "customerid",
        is_sensible=True,
        sensitivity_strategy="obfuscate",
    ),
    _optional("reviewstatus-first", "reviewstatus_first", "reviewstatus_first"),
    _outcome("marcacion-final", "marcacion_final", "marcacion_final"),
    _outcome("razon-marcacion", "razon_marcacion", "razon_marcacion"),
    _optional("biocatch-score", "biocatch_score", "biocatch_score", "number"),
    _optional("model-score", "model_score", "Model_score", "number"),
    _optional(
        "fecha-primer-marcacion",
        "fecha_primer_marcacion",
        "fecha_primer_marcacion",
        "datetime",
    ),
    _optional(
        "fecha-ultima-marcacion",
        "fecha_ultima_marcacion",
        "fecha_ultima_marcacion",
        "datetime",
    ),
    _optional("biocatch-is-mobile-rat", "biocatch_isMobileRat", "biocatch_isMobileRat"),
    _optional("biocatch-is-emulator", "biocatch_isEmulator", "biocatch_isEmulator"),
    _optional("biocatch-is-rat", "biocatch_isRat", "biocatch_isRat"),
    _optional("biocatch-is-bot", "biocatch_isBot", "biocatch_isBot"),
    _optional("biocatch-indrobo1", "biocatch_indrobo1", "biocatch_indrobo1"),
    _optional("biocatch-is-on-call", "biocatch_isOnCall", "biocatch_isOnCall"),
    _optional(
        "biocatch-is-voip-on-call", "biocatch_isVoipOnCall", "biocatch_isVoipOnCall"
    ),
    _optional(
        "biocatch-screen-broadcast",
        "biocatch_screenBroadcast",
        "biocatch_screenBroadcast",
    ),
    _optional("device-id", "deviceid", "deviceid"),
    _optional("triggered-rules", "triggered_rules", "triggered_rules"),
    _optional(
        "device-ip-encrypted",
        "device_ipaddress_encrypted",
        "device_ipaddress_encrypted",
    ),
    _optional(
        "counterparty-entity-encrypted",
        "counterpartyentityid_encrypted",
        "counterpartyentityid_encrypted",
    ),
    _optional("transaction-id", "transactionid", "transactionid"),
    _outcome("output-tags", "output_tags", "output_tags"),
    _optional("lista-cliente", "lista_cliente", "lista_cliente"),
    _optional("tipo-documento", "tipo_documento", "tipo_documento"),
    _optional("numero-documento", "numero_documento", "numero_documento"),
    _optional("nombre-razon-social", "nombre_razon_social", "nombre_razon_social"),
    _optional("fecha-nacimiento", "fecha_nacimiento", "fecha_nacimiento", "date"),
    _optional("sexo", "sexo", "sexo"),
    _optional(
        "fecha-expedicion-documento",
        "fecha_expedicion_documento",
        "fecha_expedicion_documento",
        "date",
    ),
    _optional(
        "indicador-revinculado", "indicador_revinculado", "indicador_revinculado"
    ),
    _optional("codigo-ciudad", "codigo_ciudad", "codigo_ciudad"),
    _optional("ciudad", "ciudad", "ciudad"),
    _optional("empleado-banco", "empleado_banco", "empleado_banco"),
    _optional("fecha-alta", "fecha_alta", "fecha_alta", "date"),
    _optional("direccion", "direccion", "direccion"),
    _optional("correo-1", "correo_1", "correo_1"),
    _optional("correo-2", "correo_2", "correo_2"),
    _optional("celular", "celular", "celular"),
    _optional(
        "fecha-ultima-modificacion",
        "fecha_ultima_modificacion",
        "fecha_ultima_modificacion",
        "datetime",
    ),
    _optional("monto-mas-alto-pse", "MontoMasAltoPSE", "MontoMasAltoPSE", "number"),
    _optional(
        "monto-mas-alto-pasarela-pago",
        "MontoMasAltoPasarelaPago",
        "MontoMasAltoPasarelaPago",
        "number",
    ),
    _optional("monto-mas-alto-breb", "MontoMasAltoBreB", "MontoMasAltoBreB", "number"),
    _optional(
        "monto-mas-alto-glomo", "MontoMasAltoGlomo", "MontoMasAltoGlomo", "number"
    ),
    _optional("monto-mas-alto-net", "MontoMasAltoNet", "MontoMasAltoNet", "number"),
    _optional(
        "monto-mas-alto-prestamo",
        "MontoMasAltoPrestamo",
        "MontoMasAltoPrestamo",
        "number",
    ),
    _optional(
        "monto-mas-alto-facturas",
        "MontoMasAltoFacturas",
        "MontoMasAltoFacturas",
        "number",
    ),
    _optional(
        "monto-mas-alto-retiros-tarjeta",
        "MontoMasAltoRetirosTarjeta",
        "MontoMasAltoRetirosTarjeta",
        "number",
    ),
    _outcome("tipo", "tipo", "tipo"),
    _optional("transacciones-json", "transacciones_json", "transacciones_json"),
    _optional("alertas-json", "alertas_json", "alertas_json"),
]

ROLES = {
    "event_id": "event-id",
    "event_time": "event-time",
    "event_type": "event-type",
    "channel": "channel",
    "entrypoint": "entrypoint",
    "amount": "amount",
    "customer_id": "customer-id",
}


def _request(
    method: str,
    path: str,
    token: str | None = None,
    payload: object | None = None,
    content_type: str = "application/json",
) -> tuple[int, object]:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if payload is not None:
        headers["Content-Type"] = content_type
        data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    request = Request(
        f"{BASE_URL}/api/v0{path}", data=data, headers=headers, method=method
    )
    try:
        with OPENER.open(request, timeout=60) as response:
            body = response.read()
            return response.status, json.loads(body) if body else None
    except HTTPError as exc:
        try:
            body = json.loads(exc.read())
        except (ValueError, json.JSONDecodeError):
            body = None
        return exc.code, body
    except URLError as exc:
        raise SystemExit(
            f"E2E seed: no se pudo conectar a {BASE_URL}: {exc.reason}"
        ) from exc


def _expect(status: int, expected: set[int], response: object, path: str) -> object:
    if status not in expected:
        detail = (
            response.get("detail", response) if isinstance(response, dict) else response
        )
        raise SystemExit(f"E2E seed: {path} respondió HTTP {status}: {detail}")
    return response


def _json(
    method: str,
    path: str,
    token: str,
    payload: object | None = None,
    expected: set[int] = {200},
) -> object:
    status, response = _request(method, path, token, payload)
    return _expect(status, expected, response, path)


def _login(email_env: str, password_env: str) -> dict:
    email, password = os.getenv(email_env), os.getenv(password_env)
    if not email or not password:
        raise SystemExit(f"E2E seed: define {email_env} y {password_env}")
    deadline = time.monotonic() + 120
    while True:
        status, response = _request(
            "POST", "/auth/login", payload={"email": email, "password": password}
        )
        if status == 200:
            return response
        # nginx can return 502 briefly after the Make target restarts API/worker.
        if status != 502 or time.monotonic() >= deadline:
            return _expect(status, {200}, response, "/auth/login")
        time.sleep(2)


def _schema_seed(manager_token: str, release_token: str) -> tuple[int, int]:
    active = _json("GET", "/alert-schema/active", manager_token, expected={200})
    versions = _json("GET", "/alert-schema/versions", manager_token)
    if active is None:
        draft = _json(
            "POST",
            "/alert-schema/drafts",
            manager_token,
            {"fields": FIELDS, "field_roles": ROLES},
            expected={201},
        )
        version = draft["version"]
        _json("POST", f"/alert-schema/versions/{version}/propose", manager_token, {})
        approved_status, approved = _request(
            "POST",
            f"/alert-schema/versions/{version}/approve",
            release_token,
            {"impact_acknowledged": True},
        )
        _expect(
            approved_status,
            {200},
            approved,
            f"/alert-schema/versions/{version}/approve",
        )
        active = approved
        versions = _json("GET", "/alert-schema/versions", manager_token)

    proposed = next((item for item in versions if item["status"] == "proposed"), None)
    if proposed is None:
        candidate_fields = [dict(item) for item in active["fields"]]
        candidate_fields = [
            item for item in candidate_fields if item["id"] != "alertas-json"
        ]
        for item in candidate_fields:
            if item["id"] == "tipo":
                item["description"] = "Desenlace real v2"
        channel = next(item for item in candidate_fields if item["id"] == "channel")
        candidate_fields.remove(channel)
        candidate_fields.append({**channel, "id": "channel-candidate"})
        candidate_fields.append(
            _optional(
                "e2e-candidate-marker", "e2e_candidate_marker", "e2e_candidate_marker"
            )
        )
        candidate_roles = {**active["field_roles"], "channel": "channel-candidate"}
        draft = _json(
            "POST",
            "/alert-schema/drafts",
            manager_token,
            {
                "fields": candidate_fields,
                "field_roles": candidate_roles,
                "based_on_version": active["version"],
            },
            expected={201},
        )
        _json(
            "POST",
            f"/alert-schema/versions/{draft['version']}/propose",
            manager_token,
            {},
        )
        proposed = draft
    return active["version"], proposed["version"]


def _upload_fixture(manager_token: str) -> None:
    datasets = _json("GET", "/datasets", manager_token)
    existing = next(
        (item for item in datasets if item.get("name") == DATASET_NAME), None
    )
    operation_id = None
    if existing is None:
        if not FIXTURE.is_file():
            raise SystemExit(f"E2E seed: no existe el fixture {FIXTURE}")
        boundary = f"----aria-e2e-{uuid.uuid4().hex}"
        body = (
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="file"; filename="{DATASET_NAME}.csv"\r\n'
                "Content-Type: text/csv\r\n\r\n"
            ).encode()
            + FIXTURE.read_bytes()
            + f"\r\n--{boundary}--\r\n".encode()
        )
        status, response = _request(
            "POST",
            "/datasets",
            manager_token,
            body,
            f"multipart/form-data; boundary={boundary}",
        )
        response = _expect(status, {200, 201, 202}, response, "/datasets")
        operation_id = response.get("async_operation_id")
    else:
        # Re-uploading an existing name is forbidden. Replace this E2E-owned
        # dataset through the public API so fixture changes are applied on
        # every clean run, then wait until its deletion is fully complete.
        status, deleted = _request("DELETE", f"/datasets/{DATASET_NAME}", manager_token)
        deleted = _expect(status, {200, 202}, deleted, f"/datasets/{DATASET_NAME}")
        operation_id = deleted.get("async_operation_id")
        if operation_id:
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                operation = _json(
                    "GET", f"/async-operations/{operation_id}/poll", manager_token
                )
                if operation.get("done"):
                    if operation.get("status") != "SUCCEEDED":
                        raise SystemExit(
                            f"E2E seed: eliminación falló: {operation.get('error') or operation.get('status')}"
                        )
                    break
                time.sleep(operation.get("retry_after_seconds") or 2)
            else:
                raise SystemExit(
                    f"E2E seed: timeout esperando eliminación {operation_id}"
                )
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            datasets = _json("GET", "/datasets", manager_token)
            if not any(item.get("name") == DATASET_NAME for item in datasets):
                break
            time.sleep(2)
        else:
            raise SystemExit(
                "E2E seed: timeout esperando eliminación del fixture previo"
            )

        boundary = f"----aria-e2e-{uuid.uuid4().hex}"
        body = (
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="file"; filename="{DATASET_NAME}.csv"\r\n'
                "Content-Type: text/csv\r\n\r\n"
            ).encode()
            + FIXTURE.read_bytes()
            + f"\r\n--{boundary}--\r\n".encode()
        )
        status, response = _request(
            "POST",
            "/datasets",
            manager_token,
            body,
            f"multipart/form-data; boundary={boundary}",
        )
        response = _expect(status, {200, 201, 202}, response, "/datasets")
        operation_id = response.get("async_operation_id")

    if operation_id:
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            operation = _json(
                "GET", f"/async-operations/{operation_id}/poll", manager_token
            )
            if operation.get("done"):
                if operation.get("status") != "SUCCEEDED":
                    raise SystemExit(
                        f"E2E seed: análisis falló: {operation.get('error') or operation.get('status')}"
                    )
                break
            time.sleep(operation.get("retry_after_seconds") or 2)
        else:
            raise SystemExit(f"E2E seed: timeout esperando análisis {operation_id}")

    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        status, summary = _request(
            "GET", f"/datasets/{DATASET_NAME}/summary", manager_token
        )
        if status == 404:
            # The upload request is accepted before the summary write becomes
            # visible through every API worker.
            time.sleep(2)
            continue
        summary = _expect(status, {200}, summary, f"/datasets/{DATASET_NAME}/summary")
        if summary.get("status") == "READY":
            return
        if summary.get("status") == "FAILED":
            raise SystemExit(f"E2E seed: análisis del dataset falló: {summary}")
        time.sleep(2)
    raise SystemExit("E2E seed: timeout esperando que el fixture quede READY")


def main() -> None:
    if not FIXTURE.is_file():
        raise SystemExit(f"E2E seed: fixture no encontrado: {FIXTURE}")
    # Keep the fixture contract visible in diagnostics without exposing rows.
    with FIXTURE.open(newline="", encoding="utf-8-sig") as source:
        columns = next(csv.reader(source))
    missing = {
        "eventid",
        "fecha_transaccion",
        "eventtype",
        "channel",
        "integrationpoint",
        "amount_value",
        "customerid",
    } - set(columns)
    if missing:
        raise SystemExit(
            f"E2E seed: faltan columnas obligatorias del fixture: {sorted(missing)}"
        )

    manager = _login("E2E_MANAGER_EMAIL", "E2E_MANAGER_PASSWORD")
    release = _login("E2E_RELEASE_MANAGER_EMAIL", "E2E_RELEASE_MANAGER_PASSWORD")
    active_version, candidate_version = _schema_seed(
        manager["access_token"], release["access_token"]
    )
    _upload_fixture(manager["access_token"])

    status, active_configuration = _request(
        "GET", "/configurations/active", manager["access_token"]
    )
    _expect(status, {200}, active_configuration, "/configurations/active")
    print(
        "E2E seed listo: "
        f"schema_active=v{active_version}, schema_candidate=v{candidate_version}, "
        f"dataset={DATASET_NAME}, active_configuration={active_configuration['configuration_id']}"
    )


if __name__ == "__main__":
    try:
        main()
    except (KeyError, TypeError) as exc:
        print(f"E2E seed: respuesta de API incompleta ({exc})", file=sys.stderr)
        raise SystemExit(1) from exc
