"""AuditLogRepository — registro persistente de eventos de auditoría."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from src.infrastructure.persistence.database.dynamodb.client import get_dynamodb_resource

log = logging.getLogger(__name__)

TABLE_NAME = "audit_log"
PARTITION  = "log"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _log_id() -> str:
    return f"{_now_iso()}#{uuid.uuid4().hex[:8]}"


class AuditLogRepository:

    def __init__(self) -> None:
        self._table = get_dynamodb_resource().Table(TABLE_NAME)

    def write(
        self,
        tipo: str,
        accion: str,
        entidad_tipo: str,
        entidad_id: str,
        detalle: str = "",
        usuario: str = "system",
    ) -> None:
        try:
            self._table.put_item(Item={
                "partition":    PARTITION,
                "log_id":       _log_id(),
                "tipo":         tipo,
                "accion":       accion,
                "entidad_tipo": entidad_tipo,
                "entidad_id":   entidad_id,
                "detalle":      detalle[:500],
                "usuario":      usuario,
                "timestamp":    _now_iso(),
            })
        except ClientError as exc:
            log.warning("AuditLogRepository.write failed: %s", exc)

    def list_recent(self, tipo: Optional[str] = None, limit: int = 100) -> list[dict]:
        try:
            if tipo:
                r = self._table.query(
                    IndexName="TipoIdx",
                    KeyConditionExpression=Key("tipo").eq(tipo),
                    ScanIndexForward=False,
                    Limit=limit,
                )
            else:
                r = self._table.query(
                    KeyConditionExpression=Key("partition").eq(PARTITION),
                    ScanIndexForward=False,
                    Limit=limit,
                )
            items = r.get("Items", [])
            items.sort(key=lambda x: x.get("log_id", ""), reverse=True)
            return items
        except ClientError as exc:
            log.error("AuditLogRepository.list_recent: %s", exc)
            return []
