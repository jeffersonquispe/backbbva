"""Clean real E2E state through the authenticated API exposed by nginx."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

_HTTP_OPENER = build_opener(ProxyHandler({}))


def _json_request(url: str, payload: dict[str, str], token: str | None = None) -> dict:
    deadline = time.monotonic() + 120
    while True:
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = Request(
            url,
            data=json.dumps(payload).encode(),
            headers=headers,
            method="POST",
        )
        try:
            with _HTTP_OPENER.open(request, timeout=30) as response:
                return json.loads(response.read())
        except HTTPError as exc:
            body = exc.read().decode(errors="replace")
            if exc.code == 502 and time.monotonic() < deadline:
                time.sleep(2)
                continue
            raise SystemExit(
                f"E2E clean: API respondió HTTP {exc.code}: {body}"
            ) from exc
        except URLError as exc:
            if time.monotonic() < deadline:
                time.sleep(2)
                continue
            raise SystemExit(
                f"E2E clean: no se pudo conectar a {url}. "
                "Levanta nginx/API y vuelve a intentar."
            ) from exc


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--yes", action="store_true", help="confirm destructive cleanup"
    )
    args = parser.parse_args()
    if not args.yes:
        raise SystemExit(
            "Refusing to clean without --yes (this deletes E2E data through the API)."
        )

    base_url = os.getenv("E2E_BASE_URL", "http://localhost").rstrip("/")
    email = os.getenv("E2E_MANAGER_EMAIL")
    password = os.getenv("E2E_MANAGER_PASSWORD")
    if not email or not password:
        raise SystemExit("E2E clean: set E2E_MANAGER_EMAIL and E2E_MANAGER_PASSWORD")

    login = _json_request(
        f"{base_url}/api/v0/auth/login",
        {"email": email, "password": password},
    )
    result = _json_request(f"{base_url}/api/v0/e2e/clean", {}, login["access_token"])
    preserved_tables = result.get("preserved_tables", [])
    preserved_names = [
        item["TableName"] if isinstance(item, dict) else str(item)
        for item in preserved_tables
    ]
    print(
        "E2E clean: deleted "
        f"{result.get('deleted_items', 0)} items through the API; "
        f"preserved tables: {', '.join(preserved_names)}"
    )


if __name__ == "__main__":
    try:
        main()
    except KeyError as exc:
        print(f"E2E clean: respuesta de login incompleta ({exc})", file=sys.stderr)
        raise SystemExit(1) from exc
