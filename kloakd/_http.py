"""
KLOAKD SDK — Shared HTTP transport layer.

Provides the _HttpTransport class used by both Kloakd (sync) and AsyncKloakd
(async). All retry logic, error mapping, and header construction lives here
— once, not once per namespace.

Retry policy:
    - Retryable: 429, 500, 502, 503, 504
    - Non-retryable: 400, 401, 403, 404
    - Strategy: exponential backoff (base * 2^attempt), cap 60s
    - 429 respects Retry-After header when present
    - Max attempts: configurable, default 3
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Optional

from kloakd.errors import (
    ApiError,
    AuthenticationError,
    KloakdError,
    NotEntitledError,
    RateLimitError,
    UpstreamError,
)

logger = logging.getLogger("kloakd.http")

_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
_SDK_VERSION = "0.1.0"


def _sdk_header(language: str = "python") -> str:
    return f"{language}/{_SDK_VERSION}"


class _HttpTransport:
    """
    Shared HTTP transport for the synchronous Kloakd client.

    Not part of the public API — do not instantiate directly.
    """

    def __init__(
        self,
        api_key: str,
        organization_id: str,
        base_url: str,
        timeout: float,
        max_retries: int,
        http_client: Optional[Any],
    ) -> None:
        self._api_key = api_key
        self._organization_id = organization_id
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._max_retries = max_retries
        self._http_client = http_client

    def _auth_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "X-Kloakd-Organization": self._organization_id,
            "X-Kloakd-SDK": _sdk_header(),
            "Content-Type": "application/json",
        }

    def _org_prefix(self) -> str:
        return f"/api/v1/organizations/{self._organization_id}"

    def _url(self, path: str) -> str:
        return f"{self._base_url}{self._org_prefix()}/{path.lstrip('/')}"

    def request(
        self,
        method: str,
        path: str,
        json_body: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        stream: bool = False,
    ) -> Any:
        """
        Execute a synchronous HTTP request with retry logic.

        Args:
            method: HTTP method (GET, POST, DELETE, etc.)
            path: Path relative to the org prefix.
            json_body: JSON request body.
            params: URL query parameters.
            stream: If True, returns the raw httpx.Response for SSE streaming.

        Returns:
            Parsed JSON dict, or raw response when stream=True.
        """
        try:
            import httpx
        except ImportError as exc:
            raise RuntimeError(
                "httpx is required: pip install kloakd-sdk[http]"
            ) from exc

        url = self._url(path)
        headers = self._auth_headers()
        if stream:
            headers["Accept"] = "text/event-stream"

        last_exc: Optional[Exception] = None

        for attempt in range(self._max_retries):
            try:
                if self._http_client is not None:
                    response = self._http_client.request(
                        method, url, json=json_body, params=params, headers=headers
                    )
                else:
                    with httpx.Client(timeout=self._timeout) as http:
                        response = http.request(
                            method, url, json=json_body, params=params, headers=headers
                        )

                if stream:
                    return response

                body: Dict[str, Any] = response.json() if response.content else {}
                self._raise_for_status(response.status_code, response.content, body)
                return body

            except KloakdError as exc:
                if not self._is_retryable(exc):
                    raise
                last_exc = exc
                wait = self._backoff(attempt, exc)
                logger.warning(
                    "Request failed (attempt %d/%d), retrying in %.1fs: %s",
                    attempt + 1,
                    self._max_retries,
                    wait,
                    exc.message,
                )
                time.sleep(wait)

        assert last_exc is not None
        raise last_exc

    def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self.request("GET", path, params=params)

    def post(self, path: str, body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self.request("POST", path, json_body=body or {})

    def delete(self, path: str) -> None:
        self.request("DELETE", path)

    @staticmethod
    def _raise_for_status(
        status_code: int,
        content: Any,
        body: Optional[Dict[str, Any]] = None,
    ) -> None:
        if status_code < 400:
            return

        if body is None:
            try:
                body = json.loads(content) if content else {}
            except Exception:
                body = {}

        detail = body.get("detail") or body.get("message") or str(content)[:200]

        if status_code == 401:
            raise AuthenticationError(f"Invalid or expired API key: {detail}")

        if status_code == 403:
            raise NotEntitledError(
                message=f"Not entitled to this module: {detail}",
                module=body.get("module", "unknown"),
                upgrade_url=body.get("upgrade_url", "https://app.kloakd.dev/billing"),
            )

        if status_code == 429:
            raise RateLimitError(
                message=f"Rate limit exceeded: {detail}",
                retry_after=int(body.get("retry_after", 60)),
                reset_at=str(body.get("reset_at", "")),
            )

        if status_code == 502:
            raise UpstreamError(f"Upstream fetch failed: {detail}")

        raise ApiError(f"KLOAKD API error {status_code}: {detail}", status_code)

    @staticmethod
    def _is_retryable(exc: KloakdError) -> bool:
        return exc.status_code in _RETRYABLE_STATUS_CODES

    @staticmethod
    def _backoff(attempt: int, exc: KloakdError) -> float:
        if isinstance(exc, RateLimitError) and exc.retry_after > 0:
            return float(exc.retry_after)
        base = 1.0 * (2**attempt)
        return min(base, 60.0)


class _AsyncHttpTransport:
    """
    Shared HTTP transport for the asynchronous AsyncKloakd client.

    Not part of the public API — do not instantiate directly.
    """

    def __init__(
        self,
        api_key: str,
        organization_id: str,
        base_url: str,
        timeout: float,
        max_retries: int,
        http_client: Optional[Any],
    ) -> None:
        self._api_key = api_key
        self._organization_id = organization_id
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._max_retries = max_retries
        self._http_client = http_client

    def _auth_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "X-Kloakd-Organization": self._organization_id,
            "X-Kloakd-SDK": _sdk_header(),
            "Content-Type": "application/json",
        }

    def _org_prefix(self) -> str:
        return f"/api/v1/organizations/{self._organization_id}"

    def _url(self, path: str) -> str:
        return f"{self._base_url}{self._org_prefix()}/{path.lstrip('/')}"

    async def request(
        self,
        method: str,
        path: str,
        json_body: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Execute an async HTTP request with retry logic."""
        import asyncio

        try:
            import httpx
        except ImportError as exc:
            raise RuntimeError(
                "httpx is required: pip install kloakd-sdk[http]"
            ) from exc

        url = self._url(path)
        headers = self._auth_headers()
        last_exc: Optional[Exception] = None

        for attempt in range(self._max_retries):
            try:
                if self._http_client is not None:
                    response = await self._http_client.request(
                        method, url, json=json_body, params=params, headers=headers
                    )
                else:
                    async with httpx.AsyncClient(timeout=self._timeout) as http:
                        response = await http.request(
                            method, url, json=json_body, params=params, headers=headers
                        )

                body: Dict[str, Any] = response.json() if response.content else {}
                _HttpTransport._raise_for_status(response.status_code, response.content, body)
                return body

            except KloakdError as exc:
                if not _HttpTransport._is_retryable(exc):
                    raise
                last_exc = exc
                wait = _HttpTransport._backoff(attempt, exc)
                logger.warning(
                    "Async request failed (attempt %d/%d), retrying in %.1fs: %s",
                    attempt + 1,
                    self._max_retries,
                    wait,
                    exc.message,
                )
                await asyncio.sleep(wait)

        assert last_exc is not None
        raise last_exc

    async def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return await self.request("GET", path, params=params)

    async def post(self, path: str, body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return await self.request("POST", path, json_body=body or {})

    async def delete(self, path: str) -> None:
        await self.request("DELETE", path)
