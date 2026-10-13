from __future__ import annotations

import httpx

from src.application.ports.event_sink_port import EventSink
from src.infrastructure.monitoring.audit_transport import audit_context_headers


class HttpEventSink(EventSink):
    """Writes generated rows into an aria-api Dataset over plain HTTP - POST
    /datasets/{name}/rows, creating the dataset empty first (POST
    /datasets/empty) if it doesn't exist yet. See EventSink's docstring for
    why this never touches aria-api's dataset storage directly."""

    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url
        self.token = token
        self._client = client or httpx.Client(base_url=base_url)

    def write_batch(self, dataset_name: str, rows: list[dict]) -> int:
        if not rows:
            return 0

        headers = self._headers()
        response = self._client.post(
            f"/datasets/{dataset_name}/rows",
            json={"rows": rows},
            headers=headers,
        )

        if response.status_code == 404:
            create_response = self._client.post(
                "/datasets/empty",
                json={"name": dataset_name, "fields": list(rows[0].keys())},
                headers=headers,
            )
            if not create_response.is_success and create_response.status_code != 409:
                raise RuntimeError(
                    f"POST /datasets/empty failed with status "
                    f"{create_response.status_code}: {create_response.text}"
                )

            response = self._client.post(
                f"/datasets/{dataset_name}/rows",
                json={"rows": rows},
                headers=headers,
            )

        if not response.is_success:
            raise RuntimeError(
                f"POST /datasets/{dataset_name}/rows failed with status "
                f"{response.status_code}: {response.text}"
            )

        return response.json()["total_rows"]

    def _headers(self) -> dict[str, str]:
        headers = audit_context_headers()
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers
