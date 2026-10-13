"""Query parameters shared by GET /metrics/* and GET /alerts/history: the
range (`from`, `to`) and the dimension filters. Each filter is repeatable
(`?channel=WEB&channel=APP` = either). A datetime without an offset is read
in the operations timezone (America/Bogota), like every metrics bucket."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import Query

from src.infrastructure.core.config import genai_config


@dataclass
class MetricsQueryParams:
    from_: datetime | None
    to: datetime | None
    filters: dict[str, list[str]] = field(default_factory=dict)


def _aware(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=ZoneInfo(genai_config.OPERATIONS_TIMEZONE))


def metrics_query_params(
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: Annotated[datetime | None, Query()] = None,
    segment: Annotated[list[str] | None, Query()] = None,
    channel: Annotated[list[str] | None, Query()] = None,
    subchannel: Annotated[list[str] | None, Query()] = None,
    amount_tier: Annotated[list[str] | None, Query()] = None,
    status: Annotated[list[str] | None, Query()] = None,
    configuration_id: Annotated[list[str] | None, Query()] = None,
    resolution_method: Annotated[list[str] | None, Query()] = None,
) -> MetricsQueryParams:
    filters = {
        "segment": segment,
        "channel": channel,
        "subchannel": subchannel,
        "amount_tier": amount_tier,
        "status": status,
        "configuration_id": configuration_id,
        "resolution_method": resolution_method,
    }
    return MetricsQueryParams(
        from_=_aware(from_),
        to=_aware(to),
        filters={name: values for name, values in filters.items() if values},
    )
