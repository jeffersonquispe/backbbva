"""Exercise final-partition global evaluation through local nginx and workers."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sys
import time
from datetime import UTC, datetime, timedelta
from datetime import time as datetime_time
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo

import boto3
from boto3.dynamodb.conditions import Attr, Key

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from e2e_agent_local import (
    bootstrap_token,
    check,
    compose,
    manager_token,
    request,
    restart_nginx,
    update_settings,
    wait_for_nginx_api,
)

from src.domain.datasets.mature_sampling import (
    MatureSampleSpec,
    deterministic_partition,
)

FAST_E2E = os.getenv("E2E_AGENT_FAST") == "1"
PRESERVE_E2E_DATA = os.getenv("E2E_PRESERVE_DATA") == "1"
BASE_ALERT_COUNT = 360 if FAST_E2E else 3_000
MINIMUM_FINAL_ROWS = 30 if FAST_E2E else 200
TABLE_NAME = "alerts"


def cleanup_synthetic_alerts() -> None:
    client = boto3.resource(
        "dynamodb",
        endpoint_url=f"http://localhost:{os.getenv('LOCAL_DYNAMODB_PORT', '8002')}",
        region_name="us-east-1",
        aws_access_key_id="local",
        aws_secret_access_key="local",
    )
    table = client.Table(TABLE_NAME)
    scan: dict[str, object] = {
        "FilterExpression": Attr("event_type").eq("H8 evaluation fixture"),
        "ProjectionExpression": "#partition, alert_id",
        "ExpressionAttributeNames": {"#partition": "partition"},
    }
    with table.batch_writer() as batch:
        while True:
            response = table.scan(**scan)
            for item in response.get("Items", []):
                batch.delete_item(
                    Key={"partition": item["partition"], "alert_id": item["alert_id"]}
                )
            last_key = response.get("LastEvaluatedKey")
            if not last_key:
                break
            scan["ExclusiveStartKey"] = last_key


# Fraud signal the replay can see without external enrichment (it never calls
# ARIC, so BioCatch flags stay unavailable): positives spend far above the
# customer's habitual amounts and highest-amount fields, towards a beneficiary
# absent from their history; negatives look like that history.
HABITUAL_AMOUNTS = (Decimal("40"), Decimal("50"), Decimal("60"))
HABITUAL_MAX_AMOUNT = Decimal("150")
FRAUD_AMOUNT = Decimal("2400")
LEGITIMATE_AMOUNT = Decimal("50")
HABITUAL_COUNTERPARTY = "Supermercado del barrio"
NEW_COUNTERPARTY = "Beneficiario nuevo"


def _synthetic_field_timestamp(
    field_name: str, alert_timestamp: datetime, index: int
) -> datetime:
    """Give KYC and event dates plausible, distinct values in local fixtures."""
    name = field_name.casefold()
    if any(token in name for token in ("nacimiento", "birth")):
        return alert_timestamp - timedelta(days=365 * (25 + index % 25))
    if any(token in name for token in ("expedicion", "expedition", "issue")):
        return alert_timestamp - timedelta(days=365 * (3 + index % 8))
    if any(token in name for token in ("alta", "onboard", "created")):
        return alert_timestamp - timedelta(days=365 * (1 + index % 10))
    if any(token in name for token in ("modificacion", "modified", "updated")):
        return alert_timestamp - timedelta(days=1 + index % 365)
    if any(
        token in name
        for token in ("event", "transaccion", "transaction", "alert", "timestamp")
    ):
        return alert_timestamp
    return alert_timestamp - timedelta(days=1 + index % 30)


def _synthetic_history(
    schema: dict,
    alert_timestamp: datetime,
    index: int,
    current_input: dict[str, object],
) -> list[dict]:
    fields = [
        field
        for field in schema["fields"]
        if field.get("is_history") and not field.get("is_sensible") and not field.get("is_label")
    ]
    history: list[dict] = []
    for history_index in range(3):
        entry: dict[str, object] = {}
        occurred_at = alert_timestamp - timedelta(days=30 * (history_index + 1))
        for field in fields:
            name = field["field"]
            normalized = name.casefold()
            if field["type"] == "number":
                if "amount" in normalized or "monto" in normalized:
                    value: object = (
                        HABITUAL_MAX_AMOUNT
                        if "alto" in normalized
                        else HABITUAL_AMOUNTS[history_index]
                    )
                else:
                    value = current_input.get(name, Decimal(1))
            elif field["type"] in {"date", "datetime"}:
                value = (
                    occurred_at.date().isoformat()
                    if field["type"] == "date"
                    else occurred_at.isoformat()
                )
            elif field["type"] == "bool":
                value = False
            elif "counterparty" in normalized:
                value = HABITUAL_COUNTERPARTY
            elif name in current_input:
                value = current_input[name]
            elif "geo" in normalized or "country" in normalized:
                value = "CO"
            elif "channel" in normalized:
                value = "APP"
            elif "type" in normalized or "tipo" in normalized:
                value = "payment"
            elif "status" in normalized or "estado" in normalized:
                value = "approved"
            else:
                value = "retail"
            entry[name] = value
        history.append(entry)
    return history


def wait_operation(token: str, operation_id: str, timeout: int = 240) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status, operation = request(
            "GET", f"/async-operations/{operation_id}/poll", token
        )
        check(status, 200, "poll async operation", operation)
        if operation["done"]:
            if operation["status"] != "SUCCEEDED":
                raise RuntimeError(
                    f"operation {operation_id} ended {operation['status']}: "
                    f"{operation.get('error')}"
                )
            return operation["result"]
        time.sleep(1)
    raise RuntimeError(f"operation {operation_id} did not finish in {timeout}s")


def wait_model(token: str, model_id: str, timeout: int = 300) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status, model = request("GET", f"/models/{model_id}", token)
        check(status, 200, "read trained model", model)
        if model["status"] == "READY":
            return model
        if model["status"] == "FAILED":
            raise RuntimeError(f"model training failed: {model.get('error')}")
        time.sleep(1)
    raise RuntimeError(f"model {model_id} did not become READY")


def wait_evaluation(token: str, snapshot_id: str, timeout: int = 120) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status, evaluation = request(
            "GET", f"/agent/objectives/evaluations/global/{snapshot_id}", token
        )
        check(status, 200, "read global evaluation", evaluation)
        if evaluation["status"] in {"SUCCEEDED", "FAILED"}:
            return evaluation
        time.sleep(0.5)
    raise RuntimeError("global pipeline evaluation did not finish")


def _mapping_and_schema(token: str) -> tuple[dict, dict, dict]:
    status, sampler_configuration = request(
        "GET", "/assistant-optimizer-settings/sampler/schema-configuration", token
    )
    check(status, 200, "read sampler schema mapping", sampler_configuration)
    mapping = sampler_configuration["mapping"]
    status, schema = request("GET", "/alert-schema/active", token)
    check(status, 200, "read active alert schema", schema)
    fields = {item["field"]: item for item in schema["fields"]}
    required = {
        mapping["initial_mark_field"],
        mapping["initial_marking_date_field"],
        mapping["target_field"],
        mapping["marking_date_field"],
    }
    if not required <= fields.keys() or fields[mapping["initial_mark_field"]].get(
        "is_mandatory", False
    ):
        status, options = request(
            "GET", "/assistant-optimizer-settings/sampler/schema-configuration", token
        )
        check(status, 200, "get current schema mapping options", options)
        option_fields = {
            key: [item["field"] for item in options[key]]
            for key in (
                "initial_mark_fields",
                "initial_marking_date_fields",
                "target_fields",
                "marking_date_fields",
            )
        }
        label_mapping = mapping.get("label_value_mapping") or {}
        if not any(value == "fraud" for value in label_mapping.values()) or not any(
            value == "no_fraud" for value in label_mapping.values()
        ):
            label_mapping = {"fraud": "fraud", "no_fraud": "no_fraud"}
        initial_marking_date = next(
            (
                name
                for name in option_fields["initial_marking_date_fields"]
                if name == "fecha_primer_marcacion"
            ),
            option_fields["initial_marking_date_fields"][0],
        )
        marking_date = next(
            (
                name
                for name in option_fields["marking_date_fields"]
                if name != initial_marking_date
                and name == "fecha_ultima_marcacion"
            ),
            next(
                name
                for name in option_fields["marking_date_fields"]
                if name != initial_marking_date
            ),
        )
        mapping = {
            # Outcome fields are excluded from the snapshot, so a mandatory
            # alert field (e.g. event_id) must never stand in as the mark.
            "initial_mark_field": next(
                (name for name in option_fields["initial_mark_fields"] if name == "reviewstatus_first"),
                next(
                    name
                    for name in option_fields["initial_mark_fields"]
                    if not fields.get(name, {}).get("is_mandatory", False)
                ),
            ),
            "initial_marking_date_field": initial_marking_date,
            "target_field": next(
                (name for name in option_fields["target_fields"] if name == "marcacion_final"),
                option_fields["target_fields"][0],
            ),
            "marking_date_field": marking_date,
            "label_value_mapping": label_mapping,
        }
        status, saved = request(
            "PUT",
            "/assistant-optimizer-settings/sampler/schema-configuration",
            token,
            mapping,
        )
        check(status, 200, "update mapping to the active schema", saved)
    # The sampler mapping may have been replaced above. Recompute reserved
    # fields before choosing a feature for fixture segmentation; otherwise an
    # initial-mark field such as event_id can be selected as the stratum and
    # then overwritten with the same constant value for every generated row.
    required = {
        mapping["initial_mark_field"],
        mapping["initial_marking_date_field"],
        mapping["target_field"],
        mapping["marking_date_field"],
    }
    positive_values = [
        key
        for key, value in mapping["label_value_mapping"].items()
        if value == "fraud"
    ]
    negative_values = [
        key
        for key, value in mapping["label_value_mapping"].items()
        if value == "no_fraud"
    ]
    if not positive_values or not negative_values:
        raise RuntimeError("active objective mapping needs both binary labels")
    numeric = next(
        (
            item["field"]
            for item in schema["fields"]
            if item["type"] == "number"
            and item["is_alert"]
            and not item["is_sensible"]
            and not item["is_label"]
            and item["field"] not in required
        ),
        None,
    )
    strata = next(
        (
            item["field"]
            for item in schema["fields"]
            if item["type"] == "string"
            and item["is_alert"]
            and not item["is_sensible"]
            and not item["is_label"]
            and item["field"] not in required
        ),
        None,
    )
    if not numeric or not strata:
        raise RuntimeError("active schema needs one numeric and one string feature")
    return mapping, schema, {
        "numeric": numeric,
        "strata": strata,
        "positive": positive_values[0],
        "negative": negative_values[0],
    }


def unused_sampler_period_days() -> int:
    """Choose a valid period that yields a fresh append-only snapshot ID."""
    client = boto3.resource(
        "dynamodb",
        endpoint_url=f"http://localhost:{os.getenv('LOCAL_DYNAMODB_PORT', '8002')}",
        region_name="us-east-1",
        aws_access_key_id="local",
        aws_secret_access_key="local",
    )
    table = client.Table("dataset_snapshots")
    used: set[int] = set()
    response = table.scan()
    while True:
        for item in response.get("Items", []):
            period = item.get("specification", {}).get("sampler_period_days")
            if isinstance(period, int):
                used.add(period)
        key = response.get("LastEvaluatedKey")
        if not key:
            break
        response = table.scan(ExclusiveStartKey=key)
    available = sorted(set(range(30, 366)) - used)
    if not available:
        raise RuntimeError("all mature-snapshot period values are already reserved")
    return secrets.choice(available)


def seed_mature_alerts(
    *, token: str, schema: dict, mapping: dict, fields: dict, maturity_days: int,
    settings: dict,
) -> tuple[str, dict[str, object]]:
    del token  # The fixture writes only generated, non-customer test alerts.
    client = boto3.resource(
        "dynamodb",
        endpoint_url=f"http://localhost:{os.getenv('LOCAL_DYNAMODB_PORT', '8002')}",
        region_name="us-east-1",
        aws_access_key_id="local",
        aws_secret_access_key="local",
    )
    table = client.Table(TABLE_NAME)
    timezone = ZoneInfo(os.getenv("OPERATIONS_TIMEZONE", "America/Bogota"))
    # The sampler's SystemClock uses UTC; derive the fixture window from that
    # same clock so host/container dates cannot diverge around local midnight.
    today = datetime.now(UTC).date()
    # Keep labels one full day beyond the maturity boundary. This remains
    # inside the sampling period and avoids date parsing/timezone edge cases.
    mature_mark_day = today - timedelta(days=max(maturity_days + 1, 1))
    created_day = mature_mark_day
    period_end = today - timedelta(days=maturity_days)
    period_start = period_end - timedelta(days=settings["sampler_period_days"] - 1)
    schema_versions = [int(value) for value in settings["sampler_compatible_schema_versions"]]
    outcome_fields = {
        field["field"]
        for field in schema["fields"]
        if field.get("field") and field.get("is_label")
    }
    outcome_fields.update(
        {
            mapping["initial_mark_field"],
            mapping["initial_marking_date_field"],
            mapping["marking_date_field"],
            mapping["target_field"],
        }
    )
    specification = {
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "as_of": today.isoformat(),
        "maturing_days": maturity_days,
        "fields": list(settings["sampler_strata"]),
        "initial_mark_field": mapping["initial_mark_field"],
        "initial_marking_date_field": mapping["initial_marking_date_field"],
        "target_field": mapping["target_field"],
        "marking_date_field": mapping["marking_date_field"],
        "label_value_mapping": dict(mapping["label_value_mapping"]),
        "excluded_outcome_fields": sorted(outcome_fields),
        "training_target_field": "fraud_label",
        "optimizer_replay_history_format": "schema_mapped_history_v1",
        "schema_versions": schema_versions,
        "sampler_period_days": settings["sampler_period_days"],
        "sampler_minimum_per_stratum": settings["sampler_minimum_per_stratum"],
        "sampler_fraud_oversampling_ratio": settings["sampler_fraud_oversampling_ratio"],
        "sampler_train_proportion": settings["sampler_train_proportion"],
        "sampler_validation_proportion": settings["sampler_validation_proportion"],
        "sampler_test_proportion": settings["sampler_test_proportion"],
        "sampler_error_margin_pct": settings["sampler_error_margin_pct"],
        "sampler_confidence_pct": settings["sampler_confidence_pct"],
        "sampler_seed_policy": settings["sampler_seed_policy"],
    }
    expected_snapshot_id = hashlib.sha256(
        json.dumps(specification, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:32]
    seed = int(expected_snapshot_id[:16], 16)
    partition_spec = MatureSampleSpec(
        as_of=today,
        period_start=period_start,
        period_end=period_end,
        maturing_days=maturity_days,
        sample_size=BASE_ALERT_COUNT,
        seed=seed,
        train_proportion=settings["sampler_train_proportion"],
        validation_proportion=settings["sampler_validation_proportion"],
        test_proportion=settings["sampler_test_proportion"],
    )
    all_alert_ids: list[str] = []
    final_ids: list[str] = []
    required_final_ids = 30 if FAST_E2E else 59
    for _ in range(10):
        all_alert_ids = [str(uuid4()) for _ in range(BASE_ALERT_COUNT)]
        final_ids = [
            alert_id for alert_id in all_alert_ids
            if deterministic_partition(alert_id, partition_spec) == "final"
        ]
        if len(final_ids) >= required_final_ids:
            break
    if len(final_ids) < required_final_ids:
        raise RuntimeError(
            "final partition is too small for this fixture: "
            f"{len(final_ids)} rows; required={required_final_ids}"
        )
    segment_values = {alert_id: "E2E_CHANNEL" for alert_id in all_alert_ids}
    if not FAST_E2E:
        segment_values.update({alert_id: "E2E_SUPPORT_29" for alert_id in final_ids[:29]})
        segment_values.update({alert_id: "E2E_SUPPORT_30" for alert_id in final_ids[29:59]})
    timestamp = datetime.combine(
        created_day, datetime_time(hour=12), tzinfo=timezone
    ).astimezone(UTC)
    marked = mature_mark_day.isoformat()
    alert_ids: list[str] = []
    try:
        for index, alert_id in enumerate(all_alert_ids):
            alert_timestamp = timestamp + timedelta(seconds=index)
            positive = index % 2 == 0
            numeric_field_name = fields["numeric"].casefold()
            transaction_amount = (
                FRAUD_AMOUNT
                if positive and any(token in numeric_field_name for token in ("amount", "monto"))
                else LEGITIMATE_AMOUNT
                if not positive and any(token in numeric_field_name for token in ("amount", "monto"))
                else Decimal(80 + index % 10)
            )
            input_data: dict[str, object] = {}
            for field in schema["fields"]:
                name = field["field"]
                if not field["is_alert"] or field["is_sensible"] or field["is_label"]:
                    continue
                # Keep optional free text absent in this mechanics fixture.
                # Placeholder strings such as "e2e-1" look like poisoned
                # alert data to the real adversarial review step and make
                # the test validate fixture quality instead of replay wiring.
                if (
                    field["type"] == "string"
                    and not field.get("is_mandatory", False)
                    and name != fields["strata"]
                    and "counterparty" not in name.casefold()
                ):
                    continue
                if name == mapping["initial_mark_field"]:
                    value: object = "e2e_initial_review"
                elif name in {
                    mapping["initial_marking_date_field"],
                    mapping["marking_date_field"],
                }:
                    value = marked
                elif name == fields["numeric"]:
                    value = FRAUD_AMOUNT if positive else LEGITIMATE_AMOUNT
                elif name == fields["strata"]:
                    value = segment_values[alert_id]
                elif field["type"] == "number":
                    normalized_name = name.casefold()
                    if "monto" in normalized_name and "alto" in normalized_name:
                        value = HABITUAL_MAX_AMOUNT
                    elif "monto" in normalized_name or "amount" in normalized_name:
                        value = transaction_amount
                    else:
                        value = Decimal(index % 90)
                elif field["type"] in {"date", "datetime"}:
                    fixture_timestamp = _synthetic_field_timestamp(
                        name, alert_timestamp, index
                    )
                    value = (
                        fixture_timestamp.date().isoformat()
                        if field["type"] == "date"
                        else fixture_timestamp.isoformat()
                    )
                elif field["type"] == "bool":
                    value = bool(index % 2)
                elif "geo" in name.casefold() or "country" in name.casefold():
                    value = "CO"
                elif "channel" in name.casefold() or "canal" in name.casefold():
                    value = "APP"
                elif "counterparty" in name.casefold():
                    value = NEW_COUNTERPARTY if positive else HABITUAL_COUNTERPARTY
                elif "type" in name.casefold() or "tipo" in name.casefold():
                    value = "payment"
                elif "status" in name.casefold() or "estado" in name.casefold():
                    value = "approved"
                else:
                    value = "retail"
                input_data[name] = value

            item = {
                "partition": "alert",
                "alert_id": alert_id,
                "created_day": created_day.isoformat(),
                "event_id": f"H8-E2E-{alert_id}",
                "event_type": "H8 evaluation fixture",
                "status": "CLOSED",
                "schema_version": int(schema["version"]),
                "input": input_data,
                "labels": {
                    mapping["target_field"]: fields["positive"]
                    if positive
                    else fields["negative"]
                },
                "history_prev_alerta": _synthetic_history(
                    schema, alert_timestamp, index, input_data
                ),
                "agent_output": {},
                "created_at": alert_timestamp.isoformat(),
                "updated_at": alert_timestamp.isoformat(),
            }
            table.put_item(Item=item)
            alert_ids.append(alert_id)
            if index == 0:
                from src.domain.datasets.mature_sampling import (
                    alert_field_date,
                    is_mature,
                    mapped_alert_label,
                )
                hydrated = SimpleNamespace(
                    input=input_data,
                    labels=item["labels"],
                    created_at=alert_timestamp,
                )
                label = mapped_alert_label(
                    hydrated, mapping["target_field"], mapping["label_value_mapping"]
                )
                mark_date = alert_field_date(hydrated, mapping["marking_date_field"])
                if not is_mature(
                    hydrated,
                    as_of=datetime.now(UTC).date(),
                    maturing_days=maturity_days,
                    target_field=mapping["target_field"],
                    marking_date_field=mapping["marking_date_field"],
                    label_value_mapping=mapping["label_value_mapping"],
                ):
                    raise RuntimeError(
                        "synthetic alert fails the shared maturity rule: "
                        f"mapped_label={label!r}, marking_date={mark_date!r}, "
                        f"as_of={datetime.now(UTC).date()}, "
                        f"maturity_days={maturity_days}"
                    )
    except Exception:
        with table.batch_writer() as batch:
            for alert_id in alert_ids:
                batch.delete_item(Key={"partition": "alert", "alert_id": alert_id})
        raise
    count = 0
    index_deadline = time.monotonic() + 30
    while count < BASE_ALERT_COUNT and time.monotonic() < index_deadline:
        count = 0
        query = {
            "IndexName": "CreatedDayIdx",
            "KeyConditionExpression": Key("created_day").eq(created_day.isoformat()),
            "Select": "COUNT",
        }
        while True:
            response = table.query(**query)
            count += response.get("Count", 0)
            if "LastEvaluatedKey" not in response:
                break
            query["ExclusiveStartKey"] = response["LastEvaluatedKey"]
        if count < BASE_ALERT_COUNT:
            time.sleep(1)
    if count < BASE_ALERT_COUNT:
        probe = table.scan(
            FilterExpression=Attr("event_type").eq("H8 evaluation fixture"),
            ProjectionExpression="created_day, created_at, alert_id",
            Limit=1,
        )
        raise RuntimeError(
            "synthetic alert fixture is not fully indexed: "
            f"index={count}/{BASE_ALERT_COUNT}, expected_day={created_day.isoformat()}, "
            f"scan_count={probe.get('Count', 0)}, scan_sample={probe.get('Items', [])}"
        )
    return expected_snapshot_id, specification


def main() -> int:
    original_bootstrap = bootstrap_token()
    temporary_bootstrap = secrets.token_urlsafe(40)
    compose(
        "up",
        "-d",
        "--force-recreate",
        "api",
        env=os.environ | {"AUTH_BOOTSTRAP_TOKEN": temporary_bootstrap},
    )
    restart_nginx()
    wait_for_nginx_api()
    try:
        token, _user_id = manager_token(temporary_bootstrap)
    except Exception:
        compose(
            "up",
            "-d",
            "--force-recreate",
            "api",
            env=os.environ | {"AUTH_BOOTSTRAP_TOKEN": original_bootstrap},
        )
        restart_nginx()
        raise
    status, original_settings = request("GET", "/assistant-optimizer-settings", token)
    check(status, 200, "read assistant optimizer settings", original_settings)
    original_mapping = request(
        "GET", "/assistant-optimizer-settings/sampler/schema-configuration", token
    )[1]["mapping"]
    mapping, schema, fields = _mapping_and_schema(token)
    settings = dict(original_settings)
    settings.update(
        sampler_enabled=True,
        # Make each run reserve a fresh snapshot ID: final-partition
        # evaluations are deliberately single-use and append-only.
        sampler_period_days=unused_sampler_period_days(),
        sampler_error_margin_pct=0.1,
        sampler_minimum_per_stratum=30,
        sampler_fraud_oversampling_ratio=1.0,
        sampler_strata=[fields["strata"]],
        sampler_compatible_schema_versions=[str(schema["version"])],
        sampler_seed_policy="fixed_per_sample",
    )
    if FAST_E2E:
        # The production policy keeps at least 100 globally eligible cases.
        # Use its supported 30-case floor only for this local smoke fixture.
        settings["objective_minimum_support_per_segment"] = 30
    try:
        # Give this run private label values so preserved fixtures and ordinary
        # local data cannot silently enlarge its evaluation population. The
        # previous mapping is restored in finally; the tagged alerts stay
        # persisted but are ineligible under that restored mapping.
        fixture_label_prefix = f"h8_e2e_{uuid4().hex}"
        mapping["label_value_mapping"] = {
            f"{fixture_label_prefix}_fraud": "fraud",
            f"{fixture_label_prefix}_no_fraud": "no_fraud",
        }
        fields["positive"] = f"{fixture_label_prefix}_fraud"
        fields["negative"] = f"{fixture_label_prefix}_no_fraud"
        status, saved_mapping = request(
            "PUT",
            "/assistant-optimizer-settings/sampler/schema-configuration",
            token,
            mapping,
        )
        check(status, 200, "isolate labels for this H8 fixture", saved_mapping)
        update_settings(token, settings)
        status, applied_settings = request(
            "GET", "/assistant-optimizer-settings", token
        )
        check(status, 200, "read applied sampler settings", applied_settings)
        if applied_settings["sampler_error_margin_pct"] != 0.1:
            raise RuntimeError("sampler precision setting did not persist")
        if applied_settings["sampler_minimum_per_stratum"] != 30:
            raise RuntimeError("sampler stratum floor did not persist")
        if not PRESERVE_E2E_DATA:
            cleanup_synthetic_alerts()
        status, operation = request(
            "POST", "/agent/objectives", token
        )
        if status == 201:
            draft = operation
            status, active = request("GET", "/agent/objectives/active", token)
            expected = active["version"] if status == 200 else None
            status, operation = request(
                "POST",
                f"/agent/objectives/{draft['version']}/activate",
                token,
                {"expected_active_version": expected},
            )
            check(status, 200, "activate global objective", operation)
        else:
            check(status, 409, "create an additional objective version", operation)
        objective = operation
        expected_snapshot_id, expected_specification = seed_mature_alerts(
            token=token,
            schema=schema,
            mapping=mapping,
            fields=fields,
            maturity_days=objective["maturing_days"],
            settings=applied_settings,
        )
        objective_table = boto3.resource(
            "dynamodb",
            endpoint_url=f"http://localhost:{os.getenv('LOCAL_DYNAMODB_PORT', '8002')}",
            region_name="us-east-1",
            aws_access_key_id="local",
            aws_secret_access_key="local",
        ).Table("agent_objectives")
        if not FAST_E2E:
            objective_table.update_item(
                Key={"objective_id": objective["objective_id"], "version": int(objective["version"])},
                UpdateExpression=(
                    "SET schema_mapping.protected_segments = :segments, "
                    "minimum_support_per_segment = :minimum_support"
                ),
                ExpressionAttributeValues={
                    ":segments": {
                        fields["strata"]: ["E2E_SUPPORT_29", "E2E_SUPPORT_30"]
                    },
                    ":minimum_support": 30,
                },
            )
        status, preview = request(
            "POST", "/assistant-optimizer-settings/sampler/preview", token, {}
        )
        check(status, 200, "preview mature evaluation population", preview)
        expected_eligible = BASE_ALERT_COUNT if FAST_E2E else None
        if expected_eligible is not None and preview["eligible_alerts"] != expected_eligible:
            raise RuntimeError(
                "H8 smoke sample is not isolated to its fixture: "
                f"{preview['eligible_alerts']} eligible alerts; "
                f"expected exactly {expected_eligible}. No prior data was removed."
            )
        if not FAST_E2E and preview["eligible_alerts"] < 2_500:
            raise RuntimeError(
                "mature evaluation fixture was not fully discovered: "
                f"{preview['eligible_alerts']} eligible alerts"
            )
        print(
            f"Muestra H8 ({'smoke' if FAST_E2E else 'completa'}): "
            f"fixture={BASE_ALERT_COUNT}, "
            f"eligible={preview['eligible_alerts']}, "
            f"estimated={preview['estimated_sample_size']}"
        )

        status, sample_operation = request(
            "POST", "/assistant-optimizer-settings/sampler/run", token, {}
        )
        check(status, 202, "start mature sample", sample_operation)
        sample = wait_operation(token, sample_operation["id"])
        snapshot_id = sample["snapshot_id"]
        if snapshot_id != expected_snapshot_id:
            snapshot_table = boto3.resource(
                "dynamodb",
                endpoint_url=f"http://localhost:{os.getenv('LOCAL_DYNAMODB_PORT', '8002')}",
                region_name="us-east-1",
                aws_access_key_id="local",
                aws_secret_access_key="local",
            ).Table("dataset_snapshots")
            actual_snapshot = snapshot_table.get_item(
                Key={"snapshot_id": snapshot_id}
            )["Item"]
            raise RuntimeError(
                "fixture snapshot specification drifted from the sampler: "
                f"expected={expected_snapshot_id}, actual={snapshot_id}, "
                f"expected_spec={json.dumps(expected_specification, sort_keys=True)}, "
                "actual_spec="
                f"{json.dumps(actual_snapshot['specification'], sort_keys=True, default=str)}"
            )
        if sample["partition_counts"].get("final", 0) < MINIMUM_FINAL_ROWS:
            raise RuntimeError(
                "reserved final partition is too small to satisfy global support "
                f"({sample['partition_counts'].get('final', 0)} rows; "
                f"partition_counts={sample['partition_counts']})"
            )

        model_payload = {
            "tag": f"h8-e2e-{secrets.token_hex(4)}",
            "description": "H8 global evaluation E2E fixture",
            "dataset_name": sample["dataset_refs"]["all"],
            "target_field": "fraud_label",
            "positive_labels": ["fraud"],
            "feature_transforms": [{"field": fields["numeric"], "kind": "numeric"}],
            "created_by": "H8 E2E",
            "training_config": {
                "n_estimators": 12,
                "max_depth": 2,
                "learning_rate": 0.1,
                "subsample": 1.0,
                "colsample_bytree": 1.0,
                "min_child_weight": 1.0,
                "early_stopping_rounds": None,
                "split_strategy": "stratified",
            },
        }

        def train_model(tag: str) -> str:
            payload = dict(model_payload, tag=tag)
            status, model = request("POST", "/models", token, payload)
            check(status, 201, "create evaluation model", model)
            status, started = request(
                "POST", f"/models/{model['id']}/train", token, {}
            )
            check(status, 202, "start model training", started)
            wait_model(token, model["id"])
            return model["id"]

        run_tag = secrets.token_hex(4)
        baseline_id = train_model(f"h8-e2e-baseline-{run_tag}")
        status, _ = request("POST", f"/models/{baseline_id}/activate", token, {})
        check(status, 200, "activate baseline model", _)
        candidate_id = train_model(f"h8-e2e-candidate-{run_tag}")

        status, started = request(
            "POST",
            "/agent/objectives/evaluations/global",
            token,
            {"snapshot_id": snapshot_id, "candidate_model_id": candidate_id},
        )
        check(status, 202, "start final-partition global evaluation", started)
        result = wait_evaluation(token, snapshot_id)
        if result["status"] != "SUCCEEDED":
            raise RuntimeError(f"global evaluation failed: {result.get('error_code')}")
        metrics = result["safe_metrics"]
        if (
            metrics.get("partition") != "final"
            or metrics.get("baseline_model_id") != baseline_id
            or metrics.get("candidate_model_id") != candidate_id
            or metrics.get("eligible_count", 0) < MINIMUM_FINAL_ROWS
            or not metrics.get("candidate")
            or not metrics.get("baseline")
        ):
            raise RuntimeError("evaluation result did not pin both models and final data")
        print(
            f"H8 E2E por nginx ({'smoke' if FAST_E2E else 'completo'}): "
            "baseline READY vs candidato READY evaluados "
            f"sobre partición final ({metrics['eligible_count']} filas etiquetadas)."
        )
        return 0
    finally:
        # Restore mutable runtime configuration. Synthetic alerts stay tagged by
        # random IDs and are removed from the local-only DynamoDB fixture table.
        update_settings(token, original_settings)
        if original_mapping != mapping:
            request(
                "PUT",
                "/assistant-optimizer-settings/sampler/schema-configuration",
                token,
                original_mapping,
            )
        if not PRESERVE_E2E_DATA:
            cleanup_synthetic_alerts()
        compose(
            "up",
            "-d",
            "--force-recreate",
            "api",
            env=os.environ | {"AUTH_BOOTSTRAP_TOKEN": original_bootstrap},
        )
        restart_nginx()


if __name__ == "__main__":
    raise SystemExit(main())
