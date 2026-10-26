from src.infrastructure.monitoring.api_endpoint_usage import summarize_endpoint_usage


def test_usage_counts_successes_failures_and_zero_traffic_operations() -> None:
    known, unmatched = summarize_endpoint_usage(
        {("get", "/api/v0/alerts/{alert_id}"), ("post", "/api/v0/alerts/test")},
        [
            {
                "accion": "http.get",
                "entidad_tipo": "http_endpoint",
                "entidad_id": "/api/v0/alerts/{alert_id}",
                "fecha": "2026-10-24T10:00:00+00:00",
                "resultado": "success",
            },
            {
                "accion": "http.get",
                "entidad_tipo": "http_endpoint",
                "entidad_id": "/api/v0/alerts/{alert_id}",
                "fecha": "2026-10-25T10:00:00+00:00",
                "resultado": "failure",
            },
            {
                "accion": "http.post",
                "entidad_tipo": "http_endpoint",
                "entidad_id": "/api/v0/new-route",
                "fecha": "2026-10-25T11:00:00+00:00",
                "resultado": "success",
            },
            {
                "accion": "dynamodb.UpdateItem",
                "entidad_tipo": "alert",
                "entidad_id": "alert-1",
                "resultado": "success",
            },
        ],
        {("get", "/api/v0/alerts/{}")},
    )

    by_key = {(item.method, item.path): item for item in known}
    assert by_key[("get", "/api/v0/alerts/{alert_id}")].requests == 2
    assert by_key[("get", "/api/v0/alerts/{alert_id}")].successes == 1
    assert by_key[("get", "/api/v0/alerts/{alert_id}")].failures == 1
    assert by_key[("get", "/api/v0/alerts/{alert_id}")].frontend_referenced
    assert by_key[("post", "/api/v0/alerts/test")].requests == 0
    assert not by_key[("post", "/api/v0/alerts/test")].frontend_referenced
    assert [item.path for item in unmatched] == ["/api/v0/new-route"]
