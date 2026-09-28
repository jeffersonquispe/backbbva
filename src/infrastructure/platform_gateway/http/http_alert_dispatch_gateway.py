from __future__ import annotations

import httpx

from src.application.ports.alert_dispatch_gateway_port import (
    AlertDispatchGateway,
    AlertDispatchResult,
)


class HttpAlertDispatchGateway(AlertDispatchGateway):
    """Crosses into aria-api's real alert-review pipeline over plain HTTP -
    POST /alerts/test. See AlertDispatchGateway's docstring for why this
    never imports aria-api's use cases directly."""

    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url
        self.token = token
        self._client = client or httpx.Client(base_url=base_url)

    def dispatch(
        self, payload: dict, *, created_by: str | None = None
    ) -> AlertDispatchResult:
        headers = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        response = self._client.post(
            "/alerts/test",
            json={"event": payload, "created_by": created_by},
            headers=headers,
        )
        if not response.is_success:
            raise RuntimeError(
                f"POST /alerts/test failed with status {response.status_code}: "
                f"{response.text}"
            )

        body = response.json()
        return AlertDispatchResult(
            alert_id=body["alert_id"],
            async_operation_id=body["async_operation_id"],
            workflow_execution_id=body["workflow_execution_id"],
            status=body["status"],
        )
