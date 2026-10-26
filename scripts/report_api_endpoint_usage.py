"""Report observed API usage from HTTP audit rows over a UTC date range."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import UTC, date, datetime
from pathlib import Path

from boto3.dynamodb.conditions import Key

backend_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(backend_root))
os.environ.setdefault("API_V0_STR", "/api/v0")
os.environ.setdefault("GENAI_ENVIRONMENT", "local")

from src.infrastructure.entrypoint.api.fastapi_app import create_app  # noqa: E402
from src.infrastructure.monitoring.api_endpoint_usage import (  # noqa: E402
    EndpointUsage,
    summarize_endpoint_usage,
)
from src.infrastructure.persistence.database.dynamodb.client import (  # noqa: E402
    get_dynamodb_resource,
)


def _operations(openapi: dict) -> set[tuple[str, str]]:
    methods = {"get", "post", "put", "patch", "delete", "options", "head"}
    return {
        (method, path)
        for path, path_item in openapi.get("paths", {}).items()
        for method in methods
        if method in path_item
    }


def _frontend_operations(openapi: dict) -> set[tuple[str, str]]:
    frontend_root = backend_root.parent / "frontend_mockup"
    checker = frontend_root / "scripts" / "check-api-contracts.mjs"
    if not checker.is_file():
        raise RuntimeError(f"Frontend API client checker not found: {checker}")
    with tempfile.TemporaryDirectory(prefix="aria-openapi-") as directory:
        spec_path = Path(directory) / "openapi.json"
        spec_path.write_text(json.dumps(openapi), encoding="utf-8")
        result = subprocess.run(
            ["node", str(checker), str(spec_path), "--frontend-json"],
            cwd=frontend_root,
            check=True,
            capture_output=True,
            text=True,
        )
    return {tuple(item.split(" ", 1)) for item in json.loads(result.stdout)}


def _read_events(start: date, end: date) -> list[dict[str, object]]:
    table = get_dynamodb_resource().Table("audit_log")
    events: list[dict[str, object]] = []
    lower_bound = f"{start.isoformat()}T00:00:00"
    upper_bound = f"{end.isoformat()}T23:59:59.999999~"
    for method in ("get", "post", "put", "patch", "delete", "options", "head"):
        response = table.query(
            IndexName="TipoIdx",
            KeyConditionExpression=Key("tipo").eq(f"http.{method}")
            & Key("log_id").between(lower_bound, upper_bound),
            ProjectionExpression="#action, entidad_tipo, entidad_id, fecha, resultado",
            ExpressionAttributeNames={"#action": "accion"},
        )
        events.extend(response.get("Items", []))
        while "LastEvaluatedKey" in response:
            response = table.query(
                IndexName="TipoIdx",
                KeyConditionExpression=Key("tipo").eq(f"http.{method}")
                & Key("log_id").between(lower_bound, upper_bound),
                ProjectionExpression="#action, entidad_tipo, entidad_id, fecha, resultado",
                ExpressionAttributeNames={"#action": "accion"},
                ExclusiveStartKey=response["LastEvaluatedKey"],
            )
            events.extend(response.get("Items", []))
    return events


def _print(rows: list[EndpointUsage], *, include_unused: bool) -> None:
    for row in rows:
        if not include_unused and row.requests == 0:
            continue
        print(
            f"{row.method.upper():7} frontend={'yes' if row.frontend_referenced else 'no ':3} "
            f"{row.path:54} requests={row.requests:8} "
            f"success={row.successes:8} failure={row.failures:8} "
            f"last_seen={row.last_seen or '-'}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-day", type=date.fromisoformat, required=True)
    parser.add_argument(
        "--to-day", type=date.fromisoformat, default=datetime.now(UTC).date()
    )
    parser.add_argument(
        "--include-unused",
        action="store_true",
        help="also print OpenAPI operations with zero recorded requests",
    )
    args = parser.parse_args(argv)
    if args.from_day > args.to_day:
        parser.error("--from-day must be earlier than or equal to --to-day")

    events = _read_events(args.from_day, args.to_day)
    openapi = create_app().openapi()
    operations = _operations(openapi)
    frontend_operations = _frontend_operations(openapi)
    known, unregistered = summarize_endpoint_usage(
        operations, events, frontend_operations
    )
    print(f"Audit window: {args.from_day} through {args.to_day} UTC")
    print(f"HTTP audit events read: {len(events)}")
    print("OpenAPI operations:")
    _print(known, include_unused=args.include_unused)
    if unregistered:
        print("Observed routes absent from OpenAPI:")
        _print(unregistered, include_unused=True)
    zero_count = sum(row.requests == 0 for row in known)
    print(
        f"OpenAPI operations with no recorded request in this window: {zero_count}/{len(known)}"
    )
    frontend_unused = sum(not row.frontend_referenced for row in known)
    both_unused = sum(
        not row.frontend_referenced and row.requests == 0 for row in known
    )
    print(
        f"OpenAPI operations without a frontend caller: {frontend_unused}/{len(known)}"
    )
    print(
        f"No frontend caller and no audited traffic in this window: {both_unused}/{len(known)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
