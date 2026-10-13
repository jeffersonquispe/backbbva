from __future__ import annotations

import base64
import hashlib
import hmac
import json

from src.infrastructure.core.config import genai_config
from src.infrastructure.monitoring.audit_context import (
    AuditContext,
    current_audit_context,
)

_CONTEXT_HEADER = "X-ARIA-Audit-Context"
_SIGNATURE_HEADER = "X-ARIA-Audit-Signature"


def audit_context_headers() -> dict[str, str]:
    context = current_audit_context()
    payload = json.dumps(
        {
            "actor_type": context.actor_type,
            "actor_id": context.actor_id,
            "worker_name": context.worker_name,
            "correlation_id": context.correlation_id,
            "parent_id": context.parent_id,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    encoded = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    signature = hmac.new(
        genai_config.AUTH_JWT_SECRET.encode(), encoded.encode(), hashlib.sha256
    ).hexdigest()
    return {_CONTEXT_HEADER: encoded, _SIGNATURE_HEADER: signature}


def audit_context_from_headers(headers: dict[str, str]) -> AuditContext | None:
    normalized = {key.lower(): value for key, value in headers.items()}
    encoded = normalized.get(_CONTEXT_HEADER.lower())
    signature = normalized.get(_SIGNATURE_HEADER.lower())
    if not encoded or not signature:
        return None
    expected = hmac.new(
        genai_config.AUTH_JWT_SECRET.encode(), encoded.encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        payload = json.loads(
            base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        )
        return AuditContext(
            actor_type=str(payload["actor_type"])[:32],
            actor_id=str(payload["actor_id"])[:256],
            worker_name=(
                str(payload["worker_name"])[:256]
                if payload.get("worker_name")
                else None
            ),
            correlation_id=str(payload["correlation_id"])[:128],
            parent_id=(
                str(payload["parent_id"])[:256] if payload.get("parent_id") else None
            ),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None
