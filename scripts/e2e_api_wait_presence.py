"""Poll and validate the latest daily alert-schema presence report via nginx."""

from __future__ import annotations

import json
import os
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

BASE_URL = os.getenv("E2E_BASE_URL", "http://localhost").rstrip("/")
OPENER = build_opener(ProxyHandler({}))


def request(path: str, token: str | None = None, payload: dict | None = None):
    headers = {"Accept": "application/json"}
    data = None
    method = "GET"
    if payload is not None:
        method = "POST"
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(f"{BASE_URL}/api/v0{path}", data=data, headers=headers, method=method)
    try:
        with OPENER.open(req, timeout=30) as response:
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
            f"E2E presence: no se pudo conectar a {BASE_URL}: {exc.reason}"
        ) from exc


def main() -> None:
    email, password = os.getenv("E2E_MANAGER_EMAIL"), os.getenv("E2E_MANAGER_PASSWORD")
    if not email or not password:
        raise SystemExit(
            "E2E presence: define E2E_MANAGER_EMAIL y E2E_MANAGER_PASSWORD"
        )
    status, auth = request(
        "/auth/login", payload={"email": email, "password": password}
    )
    if status != 200:
        raise SystemExit(f"E2E presence: login respondió HTTP {status}")
    token = auth["access_token"]

    deadline = time.monotonic() + 120
    report = None
    while time.monotonic() < deadline:
        status, report = request("/alert-schema/presence", token)
        if status == 200 and report is not None:
            break
        if status not in {200, 404}:
            detail = report.get("detail") if isinstance(report, dict) else report
            raise SystemExit(f"E2E presence: lectura respondió HTTP {status}: {detail}")
        time.sleep(2)
    else:
        raise SystemExit("E2E presence: timeout esperando el reporte diario")

    status, active = request("/alert-schema/active", token)
    if status != 200 or active is None:
        raise SystemExit("E2E presence: no existe esquema activo")
    if report["schema_version"] != active["version"]:
        raise SystemExit(
            f"E2E presence: reporte v{report['schema_version']} no coincide con esquema activo v{active['version']}"
        )

    role_ids = set(active["field_roles"].values())
    fields = report.get("fields", [])
    by_id = {item["field_id"]: item for item in fields}
    missing = role_ids - by_id.keys()
    if missing:
        raise SystemExit(
            f"E2E presence: faltan roles obligatorios en el reporte: {sorted(missing)}"
        )
    if any(by_id[field_id].get("distribution") is None for field_id in role_ids):
        raise SystemExit(
            "E2E presence: faltan distribuciones para campos asignados a roles"
        )
    if any(not item.get("location") for item in fields):
        raise SystemExit("E2E presence: hay campos de reporte sin ubicación")

    status, suggestions = request("/alert-schema/suggestions", token)
    if status != 200 or not isinstance(suggestions, list):
        raise SystemExit(f"E2E presence: sugerencias no accesibles (HTTP {status})")
    print(
        "E2E presence listo: "
        f"report_day={report['report_day']}, schema=v{report['schema_version']}, "
        f"alerts={report['alert_count']}, fields={len(fields)}, suggestions={len(suggestions)}"
    )


if __name__ == "__main__":
    try:
        main()
    except (KeyError, TypeError) as exc:
        print(f"E2E presence: respuesta de API incompleta ({exc})", file=sys.stderr)
        raise SystemExit(1) from exc
