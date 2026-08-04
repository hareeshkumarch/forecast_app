from __future__ import annotations

import time
from typing import Any

import httpx
import polars as pl

from app.connectors.base import ConnectorAdapter, FormField, TableInfo, TestOutcome
from app.core.errors import ConnectorError
from app.models.enums import ConnectorStatus, ConnectorType

ARRAY_KEYS = ("data", "results", "items", "records", "rows", "value", "payload")

REQUEST_TIMEOUT = httpx.Timeout(15.0, connect=8.0)


class RestApiAdapter(ConnectorAdapter):
    type = ConnectorType.REST_API
    display_name = "REST API"
    supports_import = True
    form_fields = (
        FormField("endpoint", "Endpoint URL", placeholder="https://api.example.com/v1/sales"),
        FormField(
            "records_path",
            "Records key",
            required=False,
            placeholder="data",
            help_text="Key holding the array, if the response wraps it. Auto-detected when blank.",
        ),
        FormField(
            "token",
            "Bearer token / API key",
            secret=True,
            required=False,
            kind="password",
        ),
    )

    def _url(self) -> str:
        url = str(self.config.get("endpoint") or "").strip()
        if not url:
            raise ConnectorError("No endpoint URL is configured.")
        if not url.lower().startswith(("http://", "https://")):
            raise ConnectorError("The endpoint must be an http:// or https:// URL.")
        return url

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        token = self.credentials.get("token", "").strip()
        if token:

            headers["Authorization"] = token if " " in token else f"Bearer {token}"
        return headers

    def test(self) -> TestOutcome:
        if self._missing_required():
            return self._not_configured()

        started = time.perf_counter()
        try:
            url = self._url()
            with httpx.Client(timeout=REQUEST_TIMEOUT, follow_redirects=True) as client:
                response = client.get(url, headers=self._headers())
        except ConnectorError as exc:
            return TestOutcome(
                ok=False, status=ConnectorStatus.ERROR, message=exc.message,
                latency_ms=self._timed(started),
            )
        except httpx.TimeoutException:
            return TestOutcome(
                ok=False,
                status=ConnectorStatus.ERROR,
                message="The endpoint timed out after 15 seconds.",
                latency_ms=self._timed(started),
            )
        except httpx.HTTPError as exc:
            return TestOutcome(
                ok=False,
                status=ConnectorStatus.ERROR,
                message=f"Request failed: {type(exc).__name__}. Check the URL is reachable.",
                latency_ms=self._timed(started),
            )

        latency = self._timed(started)

        if response.status_code == 401:
            return TestOutcome(
                ok=False,
                status=ConnectorStatus.ERROR,
                message="The endpoint returned 401 Unauthorized. Check the token.",
                latency_ms=latency,
            )
        if response.status_code == 403:
            return TestOutcome(
                ok=False,
                status=ConnectorStatus.ERROR,
                message="The endpoint returned 403 Forbidden. The token lacks access.",
                latency_ms=latency,
            )
        if response.status_code >= 400:
            return TestOutcome(
                ok=False,
                status=ConnectorStatus.ERROR,
                message=f"The endpoint returned HTTP {response.status_code}.",
                latency_ms=latency,
            )

        try:
            records = self._extract(response.json())
        except ConnectorError as exc:
            return TestOutcome(
                ok=False, status=ConnectorStatus.ERROR, message=exc.message, latency_ms=latency
            )
        except ValueError:
            return TestOutcome(
                ok=False,
                status=ConnectorStatus.ERROR,
                message="The endpoint responded, but the body is not valid JSON.",
                latency_ms=latency,
            )

        return TestOutcome(
            ok=True,
            status=ConnectorStatus.CONNECTED,
            message=f"Connected. {len(records)} record(s) returned.",
            latency_ms=latency,
            server_version=response.headers.get("server"),
        )

    def _extract(self, body: Any) -> list[dict[str, Any]]:
        configured = str(self.config.get("records_path") or "").strip()

        if configured:
            current: Any = body
            for part in configured.split("."):
                if not isinstance(current, dict) or part not in current:
                    raise ConnectorError(
                        f"The records key '{configured}' was not found in the response."
                    )
                current = current[part]
            body = current

        if isinstance(body, list):
            records = body
        elif isinstance(body, dict):
            for key in ARRAY_KEYS:
                if isinstance(body.get(key), list):
                    records = body[key]
                    break
            else:

                records = [body]
        else:
            raise ConnectorError(
                "The response is neither a JSON array nor an object, so it can't be tabulated."
            )

        rows = [r for r in records if isinstance(r, dict)]
        if not rows and records:
            raise ConnectorError(
                "The response array contains scalars, not objects. "
                "Point 'Records key' at an array of objects."
            )
        return rows

    def list_tables(self) -> list[TableInfo]:
        frame = self.fetch(schema=None, table=None, query=None, limit=200)
        return [
            TableInfo(
                schema_name="rest",
                table_name=self._url().rsplit("/", 1)[-1] or "response",
                row_estimate=frame.height,
                columns=[
                    (name, str(dtype), frame[name].null_count() > 0)
                    for name, dtype in zip(frame.columns, frame.dtypes, strict=True)
                ],
            )
        ]

    def fetch(
        self, *, schema: str | None, table: str | None, query: str | None, limit: int
    ) -> pl.DataFrame:
        url = self._url()
        try:
            with httpx.Client(timeout=REQUEST_TIMEOUT, follow_redirects=True) as client:
                response = client.get(url, headers=self._headers())
                response.raise_for_status()
                records = self._extract(response.json())
        except httpx.HTTPStatusError as exc:
            raise ConnectorError(
                f"The endpoint returned HTTP {exc.response.status_code}."
            ) from exc
        except httpx.HTTPError as exc:
            raise ConnectorError(f"Request failed: {type(exc).__name__}.") from exc
        except ValueError as exc:
            raise ConnectorError("The response body is not valid JSON.") from exc

        if not records:
            raise ConnectorError("The endpoint returned no records.")


        flattened = [
            {
                key: (value if not isinstance(value, dict | list) else str(value))
                for key, value in record.items()
            }
            for record in records[:limit]
        ]
        return pl.DataFrame(flattened, infer_schema_length=None)
