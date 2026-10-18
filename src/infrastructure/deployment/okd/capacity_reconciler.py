"""Apply ARIA's operational capacity limits to the OKD KEDA objects."""

from __future__ import annotations

import json
import logging
import ssl
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from src.infrastructure.core.config import genai_config
from src.infrastructure.persistence.database.dynamodb.repositories.operational_settings_repository import (
    DynamoOperationalSettingsRepository,
)

logger = logging.getLogger(__name__)

_SCALED_OBJECTS = (
    ("aria-worker-main", "max_instances"),
    ("aria-worker-test", "max_test_instances"),
)


def _patch_scaled_object(name: str, maximum: int, autoscale: bool) -> None:
    token_path = "/var/run/secrets/kubernetes.io/serviceaccount/token"
    ca_path = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
    with open(token_path, encoding="utf-8") as token_file:
        token = token_file.read().strip()
    with open(
        "/var/run/secrets/kubernetes.io/serviceaccount/namespace", encoding="utf-8"
    ) as namespace_file:
        namespace = namespace_file.read().strip()

    context = ssl.create_default_context(cafile=ca_path)
    request = Request(
        "https://kubernetes.default.svc/apis/keda.sh/v1alpha1/namespaces/"
        f"{namespace}/scaledobjects/{name}",
        data=json.dumps(
            {
                "spec": {
                    "minReplicaCount": 0 if autoscale else 1,
                    "maxReplicaCount": maximum if autoscale else 1,
                }
            }
        ).encode(),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/merge-patch+json",
        },
        method="PATCH",
    )
    with urlopen(request, context=context, timeout=10) as response:
        if response.status >= 300:
            raise RuntimeError(f"KEDA patch failed for {name}: HTTP {response.status}")


def reconcile_capacity() -> None:
    if genai_config.DEPLOYMENT_TYPE.lower() != "okd":
        logger.info("Capacity reconciliation skipped for deployment type %s", genai_config.DEPLOYMENT_TYPE)
        return

    settings = DynamoOperationalSettingsRepository().get()
    for scaled_object, setting_name in _SCALED_OBJECTS:
        maximum = int(getattr(settings, setting_name))
        try:
            _patch_scaled_object(scaled_object, maximum, settings.auto_scale)
        except HTTPError as error:
            logger.exception("Could not update KEDA ScaledObject %s", scaled_object)
            raise RuntimeError(
                f"KEDA API returned HTTP {error.code} for {scaled_object}"
            ) from error
        logger.info(
            "Applied capacity settings to %s (autoscale=%s, minimum=%d, maximum=%d)",
            scaled_object,
            settings.auto_scale,
            0 if settings.auto_scale else 1,
            maximum,
        )


if __name__ == "__main__":
    logging.basicConfig(level=genai_config.DEFAULT_LOGGING_LEVEL)
    reconcile_capacity()
