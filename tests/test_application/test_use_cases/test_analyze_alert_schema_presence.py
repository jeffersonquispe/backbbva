from datetime import UTC, date, datetime
from uuid import uuid4

from src.application.ports.alert_port import AlertRecord, AlertStatus
from src.application.ports.alert_schema_port import (
    AlertSchemaDataSource,
    AlertSchemaField,
    AlertSchemaFieldType,
    AlertSchemaPresenceField,
    AlertSchemaPresenceReport,
    AlertSchemaVersion,
)
from src.application.ports.object_storage_port import ObjectStorageRef
from src.application.use_cases.alert_schema.analyze_presence import (
    AnalyzeAlertSchemaPresenceUseCase,
)


class InMemoryAlerts:
    def __init__(self, alerts):
        self.alerts = alerts

    def list_by_created_day(self, day):
        return [alert for alert in self.alerts if alert.created_at.date() == day]


class InMemorySchemas:
    def __init__(self, schema):
        self.schema = schema

    def get_active(self):
        return self.schema


class InMemoryReports:
    def __init__(self, reports=()):
        self.reports = {report.report_day: report for report in reports}
        self.saved = []

    def save(self, report):
        self.reports[report.report_day] = report
        self.saved.append(report)
        return report

    def get(self, day):
        return self.reports.get(day)

    def get_latest(self):
        return max(
            self.reports.values(), key=lambda report: report.report_day, default=None
        )

    def list_before(self, day, limit=30):
        return sorted(
            (report for report in self.reports.values() if report.report_day < day),
            key=lambda report: report.report_day,
            reverse=True,
        )[:limit]


class InMemoryObjectStorage:
    def __init__(self, payloads):
        self.payloads = payloads

    def get_bytes(self, key):
        return self.payloads[key]


def alert(day, payload, storage, created_hour=10):
    created = datetime(day.year, day.month, day.day, created_hour, tzinfo=UTC)
    key = f"raw/{uuid4()}"
    storage[key] = __import__("json").dumps(payload).encode()
    return AlertRecord(
        uuid4(),
        "event",
        "purchase",
        AlertStatus.CLOSED,
        created,
        created,
        raw_payload_ref=ObjectStorageRef("bucket", key, key),
    )


def test_presence_distribution_trend_unknown_locations_and_sensitive_example():
    day = date(2026, 10, 9)
    payloads = {}
    fields = [
        AlertSchemaField(
            "amount",
            AlertSchemaDataSource.ARIC,
            "amount",
            field_ds_loc="amount",
            type=AlertSchemaFieldType.NUMBER,
        ),
        AlertSchemaField(
            "customer",
            AlertSchemaDataSource.ARIC,
            "customer_id",
            field_ds_loc="customer.id",
            is_sensible=True,
            sensitivity_strategy="obfuscate",
        ),
    ]
    schema = AlertSchemaVersion(
        version=3, fields=fields, field_roles={"amount": "amount"}
    )
    prior = AlertSchemaPresenceReport(
        date(2026, 10, 8),
        datetime.now(UTC),
        3,
        1,
        [AlertSchemaPresenceField("amount", "amount", "amount", 1)],
    )
    use_case = AnalyzeAlertSchemaPresenceUseCase(
        InMemoryAlerts(
            [
                alert(
                    day,
                    {
                        "amount": 100,
                        "customer": {"id": "12345678"},
                        "new": {"path": "x"},
                    },
                    payloads,
                ),
                alert(day, {"amount": 200, "new": {"path": "x"}}, payloads, 11),
            ]
        ),
        InMemorySchemas(schema),
        InMemoryReports([prior]),
        InMemoryObjectStorage(payloads),
    )

    report = use_case.execute(day)

    assert report is not None
    assert report.alert_count == 2
    amount = report.fields[0]
    assert amount.present_count == 2
    assert amount.trend["delta"] == 1
    assert amount.distribution == {
        "kind": "numeric",
        "count": 2,
        "percentiles": {"p25": 125.0, "p50": 150.0, "p75": 175.0, "p95": 195.0},
    }
    customer = report.fields[1]
    assert customer.example == "****5678"
    assert report.unknown_locations[0].location == "new.path"
    assert report.unknown_locations[0].frequency == 2
