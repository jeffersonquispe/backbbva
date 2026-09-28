from __future__ import annotations

import random

import httpx

from src.application.ports.dataset_reader_gateway_port import DatasetReaderGateway

_WINDOW_LIMIT = 500


class HttpDatasetReaderGateway(DatasetReaderGateway):
    """Reads one random row out of an existing aria-api Dataset over plain
    HTTP - GET /datasets/{name}/rows. See DatasetReaderGateway's docstring
    for why this never touches aria-api's dataset storage directly."""

    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url
        self.token = token
        self._client = client or httpx.Client(base_url=base_url)

    def sample_row(self, dataset_name: str, rng: random.Random) -> dict | None:
        headers = self._headers()
        response = self._client.get(
            f"/datasets/{dataset_name}/rows",
            params={"offset": 0, "limit": _WINDOW_LIMIT},
            headers=headers,
        )
        if response.status_code == 404:
            return None
        if not response.is_success:
            raise RuntimeError(
                f"GET /datasets/{dataset_name}/rows failed with status "
                f"{response.status_code}: {response.text}"
            )

        body = response.json()
        rows = body["rows"]
        total = body["total"]

        if total == 0:
            return None

        if total <= len(rows):
            return rng.choice(rows)

        offset = rng.randrange(total)
        second_response = self._client.get(
            f"/datasets/{dataset_name}/rows",
            params={"offset": offset, "limit": 1},
            headers=headers,
        )
        if second_response.status_code == 404:
            return None
        if not second_response.is_success:
            raise RuntimeError(
                f"GET /datasets/{dataset_name}/rows failed with status "
                f"{second_response.status_code}: {second_response.text}"
            )

        second_rows = second_response.json()["rows"]
        return second_rows[0] if second_rows else None

    def _headers(self) -> dict[str, str]:
        if self.token:
            return {"Authorization": f"Bearer {self.token}"}
        return {}
