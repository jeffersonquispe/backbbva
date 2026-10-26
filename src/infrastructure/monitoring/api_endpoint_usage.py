"""Aggregate HTTP endpoint audit events against the API's OpenAPI operations."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EndpointUsage:
    method: str
    path: str
    frontend_referenced: bool = False
    requests: int = 0
    successes: int = 0
    failures: int = 0
    last_seen: str | None = None


def summarize_endpoint_usage(
    operations: set[tuple[str, str]],
    events: list[dict[str, object]],
    frontend_operations: set[tuple[str, str]] | None = None,
) -> tuple[list[EndpointUsage], list[EndpointUsage]]:
    """Return OpenAPI operations and observed endpoints absent from OpenAPI.

    Audit rows use ``accion=http.<method>`` and ``entidad_id=<route template>``.
    Unmatched routes are returned separately so routing/configuration mistakes
    are visible instead of being silently dropped from the report.
    """
    frontend_operations = frontend_operations or set()
    counts: dict[tuple[str, str], dict[str, object]] = {}
    for method, path in operations:
        counts[(method.lower(), path)] = {
            "requests": 0,
            "successes": 0,
            "failures": 0,
            "last_seen": None,
        }

    for event in events:
        if event.get("entidad_tipo") != "http_endpoint":
            continue
        action = str(event.get("accion", ""))
        if not action.startswith("http."):
            continue
        key = (action.removeprefix("http.").lower(), str(event.get("entidad_id") or ""))
        state = counts.setdefault(
            key,
            {"requests": 0, "successes": 0, "failures": 0, "last_seen": None},
        )
        state["requests"] = int(state["requests"]) + 1
        outcome_key = "successes" if event.get("resultado") == "success" else "failures"
        state[outcome_key] = int(state[outcome_key]) + 1
        occurred_at = str(event.get("fecha", "")) or None
        if occurred_at and (
            state["last_seen"] is None or occurred_at > state["last_seen"]
        ):
            state["last_seen"] = occurred_at

    known: list[EndpointUsage] = []
    unregistered: list[EndpointUsage] = []
    for (method, path), state in sorted(counts.items()):
        usage = EndpointUsage(
            method=method,
            path=path,
            frontend_referenced=any(
                _operation_shape_matches((method, path), frontend_operation)
                for frontend_operation in frontend_operations
            ),
            requests=int(state["requests"]),
            successes=int(state["successes"]),
            failures=int(state["failures"]),
            last_seen=state["last_seen"],
        )
        (
            known
            if (method, path) in {(m.lower(), p) for m, p in operations}
            else unregistered
        ).append(usage)
    return known, unregistered


def _operation_shape_matches(
    backend_operation: tuple[str, str], frontend_operation: tuple[str, str]
) -> bool:
    backend_method, backend_path = backend_operation
    frontend_method, frontend_path = frontend_operation
    if backend_method != frontend_method:
        return False
    backend_segments = backend_path.split("/")
    frontend_segments = frontend_path.split("/")
    return len(backend_segments) == len(frontend_segments) and all(
        _is_parameter(backend_part)
        or _is_parameter(frontend_part)
        or backend_part == frontend_part
        for backend_part, frontend_part in zip(backend_segments, frontend_segments)
    )


def _is_parameter(segment: str) -> bool:
    return segment == "{}" or (segment.startswith("{") and segment.endswith("}"))
