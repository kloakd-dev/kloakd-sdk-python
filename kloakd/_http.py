"""
KLOAKD SDK — Shared HTTP transport layer.

Provides the _HttpTransport class used by Kloakd (sync) and _AsyncHttpTransport
used by AsyncKloakd. All retry logic, error mapping, header construction and
Server-Sent Events parsing live here — once, not once per namespace.

Retry policy:
    - Retryable: 429 ``rate_limited``, 500, 502, 503, 504
    - Non-retryable: 400, 401, 402, 403, 404, 429 ``gb_exhausted``
    - 429 and 503 honour Retry-After (header, else the body's retry_after)
    - Otherwise exponential backoff (1s * 2^attempt), cap 60s
    - Attempts: ``max_retries`` (default 3)
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, AsyncIterator, Dict, Iterator, Mapping, Optional, Tuple

from kloakd._handoff import PollOptions, expired, is_handoff, next_interval, outcome
from kloakd.errors import (
    ApiError,
    AuthenticationError,
    BillingUnavailableError,
    JobTimeoutError,
    KloakdError,
    NotEntitledError,
    PaymentRequiredError,
    QuotaExceededError,
    RateLimitError,
    UpstreamError,
)

logger = logging.getLogger("kloakd.http")

_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
_SDK_VERSION = "0.4.0"


def _sdk_header(language: str = "python") -> str:
    return f"{language}/{_SDK_VERSION}"


def _httpx() -> Any:
    try:
        import httpx
    except ImportError as exc:  # pragma: no cover - httpx is a dependency
        raise RuntimeError("httpx is required: pip install kloakd-sdk") from exc
    return httpx


def raise_for_status(
    status_code: int,
    content: Any = b"",
    body: Optional[Dict[str, Any]] = None,
    headers: Optional[Mapping[str, str]] = None,
) -> None:
    """Map a non-2xx response to the matching KloakdError subclass.

    The API puts its error in ``detail``: a string, or an object
    ``{"error": ..., "message": ...}``. Both are read.
    """
    if status_code < 400:
        return
    if body is None:
        try:
            body = json.loads(content) if content else {}
        except Exception:
            body = {}
    raw_detail = body.get("detail")
    detail_obj: Dict[str, Any] = raw_detail if isinstance(raw_detail, dict) else body
    code = str(detail_obj.get("error") or "")
    if isinstance(raw_detail, str):
        detail = raw_detail
    else:
        detail = (
            detail_obj.get("message")
            or body.get("message")
            or code
            or (str(content)[:200] if content else f"HTTP {status_code}")
        )
    retry_header: Optional[float] = None
    if headers is not None:
        value = headers.get("retry-after") or headers.get("Retry-After")
        try:
            retry_header = float(value) if value is not None else None
        except ValueError:
            retry_header = None

    if status_code == 401:
        raise AuthenticationError(f"Invalid or expired API key: {detail}")
    if status_code == 402:
        raise PaymentRequiredError(
            str(detail),
            upgrade_url=detail_obj.get(
                "upgrade_url", "https://app.kloakd.dev/settings/billing"
            ),
        )
    if status_code == 403:
        raise NotEntitledError(
            message=f"Not entitled to this module: {detail}",
            module=detail_obj.get("module", "unknown"),
            upgrade_url=detail_obj.get("upgrade_url", "https://app.kloakd.dev/billing"),
        )
    if status_code == 429:
        if code == "gb_exhausted":
            raise QuotaExceededError(
                str(detail),
                tier=str(detail_obj.get("tier", "")),
                upgrade_url=detail_obj.get(
                    "upgrade_url", "https://app.kloakd.dev/settings/billing"
                ),
            )
        retry_after = (
            retry_header
            if retry_header is not None
            else detail_obj.get("retry_after", 60)
        )
        raise RateLimitError(
            message=f"Rate limit exceeded: {detail}",
            retry_after=int(float(retry_after)),
            reset_at=str(detail_obj.get("reset_at", "")),
        )
    if status_code == 502:
        raise UpstreamError(f"Upstream fetch failed: {detail}")
    if status_code == 503 and code == "billing_unavailable":
        raise BillingUnavailableError(
            str(detail), retry_after=retry_header if retry_header is not None else 30.0
        )
    raise ApiError(f"KLOAKD API error {status_code}: {detail}", status_code)


def _is_retryable(exc: KloakdError) -> bool:
    if isinstance(exc, (QuotaExceededError, PaymentRequiredError)):
        return False
    return exc.status_code in _RETRYABLE_STATUS_CODES


def _backoff(attempt: int, exc: KloakdError) -> float:
    if isinstance(exc, RateLimitError) and exc.retry_after >= 0:
        return min(float(exc.retry_after), 60.0)
    if isinstance(exc, BillingUnavailableError) and exc.retry_after >= 0:
        return min(float(exc.retry_after), 60.0)
    return min(float(2.0**attempt), 60.0)


def _parse_sse_lines(lines: Iterator[str]) -> Iterator[Tuple[str, Dict[str, Any]]]:
    event = ""
    for line in lines:
        line = line.strip()
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data = line[5:].strip()
            if not data:
                continue
            try:
                yield event, json.loads(data)
            except json.JSONDecodeError:
                continue


class _TransportBase:
    def __init__(
        self,
        api_key: str,
        organization_id: str,
        base_url: str,
        timeout: float,
        max_retries: int,
        http_client: Optional[Any],
        poll: Optional[PollOptions] = None,
    ) -> None:
        self._poll = poll or PollOptions()
        self._api_key = api_key
        self._organization_id = organization_id
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._max_retries = max(1, max_retries)
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

    def _poll_url(self, poll_url: str) -> str:
        """A 202's ``poll_url`` (a path from the API root) as a URL on the
        base URL. A full URL is accepted only on the base URL itself, since
        the poll carries the API key."""
        if poll_url.startswith(("http://", "https://")):
            if not poll_url.startswith(self._base_url + "/"):
                raise KloakdError(
                    f"Refusing to poll {poll_url}: not on {self._base_url}"
                )
            return poll_url
        return f"{self._base_url}/{poll_url.lstrip('/')}"

    # Kept for callers of the 0.2 static API.
    _raise_for_status = staticmethod(raise_for_status)
    _is_retryable = staticmethod(_is_retryable)
    _backoff = staticmethod(_backoff)


class _HttpTransport(_TransportBase):
    """
    Shared HTTP transport for the synchronous Kloakd client.

    Not part of the public API — do not instantiate directly.
    """

    def request(
        self,
        method: str,
        path: str,
        json_body: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Execute a synchronous HTTP request with retry logic; returns parsed JSON."""
        return self._send(method, self._url(path), json_body, params)[1]

    def _send(
        self,
        method: str,
        url: str,
        json_body: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Tuple[int, Any]:
        """One request to ``url`` with retries; returns (status code, parsed JSON)."""
        httpx = _httpx()
        headers = self._auth_headers()
        last_exc: Optional[KloakdError] = None

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
                body: Any = response.json() if response.content else {}
                raise_for_status(
                    response.status_code,
                    response.content,
                    body if isinstance(body, dict) else {},
                    response.headers,
                )
                return response.status_code, body
            except KloakdError as exc:
                if not _is_retryable(exc):
                    raise
                last_exc = exc
                if attempt + 1 < self._max_retries:
                    wait = _backoff(attempt, exc)
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

    def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        return self.request("GET", path, params=params)

    def post_following(
        self,
        path: str,
        body: Optional[Dict[str, Any]] = None,
        poll: Optional[PollOptions] = None,
    ) -> Any:
        """POST; a 202 hand-off is followed to the job's result (see _handoff)."""
        status, raw = self._send("POST", self._url(path), json_body=body or {})
        if not is_handoff(status, raw):
            return raw
        return self.follow(raw["job_id"], self._poll_url(raw["poll_url"]), poll)

    def follow(
        self, job_id: str, url: str, poll: Optional[PollOptions] = None
    ) -> Dict[str, Any]:
        """Poll a job's state at ``url`` until it completes; returns its result."""
        poll = poll or self._poll
        deadline = time.monotonic() + poll.timeout
        interval = poll.interval
        while True:
            if time.monotonic() + interval > deadline:
                raise JobTimeoutError(f"Job {job_id} still running", job_id)
            time.sleep(interval)
            try:
                _, state = self._send("GET", url)
            except KloakdError as exc:
                gone = expired(exc, job_id)
                if gone is not None:
                    raise gone from exc
                raise
            result = outcome(state, job_id)
            if result is not None:
                return result
            interval = next_interval(interval)

    def post(self, path: str, body: Optional[Dict[str, Any]] = None) -> Any:
        return self.request("POST", path, json_body=body or {})

    def put(self, path: str, body: Optional[Dict[str, Any]] = None) -> Any:
        return self.request("PUT", path, json_body=body or {})

    def patch(
        self,
        path: str,
        body: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Any:
        return self.request("PATCH", path, json_body=body or {}, params=params)

    def delete(self, path: str) -> None:
        self.request("DELETE", path)

    def iter_sse(
        self,
        method: str,
        path: str,
        body: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Iterator[Tuple[str, Dict[str, Any]]]:
        """Open a Server-Sent Events stream; yields ``(event, data)`` pairs."""
        httpx = _httpx()
        headers = {**self._auth_headers(), "Accept": "text/event-stream"}
        kwargs: Dict[str, Any] = {"params": params, "headers": headers}
        if body is not None:
            kwargs["json"] = body
        client = self._http_client or httpx.Client(timeout=None)
        try:
            with client.stream(method, self._url(path), **kwargs) as response:
                if response.status_code >= 400:
                    response.read()
                    raise_for_status(
                        response.status_code, response.content, None, response.headers
                    )
                yield from _parse_sse_lines(response.iter_lines())
        finally:
            if self._http_client is None:
                client.close()


class _AsyncHttpTransport(_TransportBase):
    """
    Shared HTTP transport for the asynchronous AsyncKloakd client.

    Not part of the public API — do not instantiate directly.
    """

    async def request(
        self,
        method: str,
        path: str,
        json_body: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Execute an async HTTP request with retry logic; returns parsed JSON."""
        return (await self._send(method, self._url(path), json_body, params))[1]

    async def _send(
        self,
        method: str,
        url: str,
        json_body: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Tuple[int, Any]:
        """One request to ``url`` with retries; returns (status code, parsed JSON)."""
        import asyncio

        httpx = _httpx()
        headers = self._auth_headers()
        last_exc: Optional[KloakdError] = None

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
                body: Any = response.json() if response.content else {}
                raise_for_status(
                    response.status_code,
                    response.content,
                    body if isinstance(body, dict) else {},
                    response.headers,
                )
                return response.status_code, body
            except KloakdError as exc:
                if not _is_retryable(exc):
                    raise
                last_exc = exc
                if attempt + 1 < self._max_retries:
                    wait = _backoff(attempt, exc)
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

    async def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        return await self.request("GET", path, params=params)

    async def post_following(
        self,
        path: str,
        body: Optional[Dict[str, Any]] = None,
        poll: Optional[PollOptions] = None,
    ) -> Any:
        """Async equivalent of _HttpTransport.post_following."""
        status, raw = await self._send("POST", self._url(path), json_body=body or {})
        if not is_handoff(status, raw):
            return raw
        return await self.follow(raw["job_id"], self._poll_url(raw["poll_url"]), poll)

    async def follow(
        self, job_id: str, url: str, poll: Optional[PollOptions] = None
    ) -> Dict[str, Any]:
        """Async equivalent of _HttpTransport.follow."""
        import asyncio

        poll = poll or self._poll
        deadline = time.monotonic() + poll.timeout
        interval = poll.interval
        while True:
            if time.monotonic() + interval > deadline:
                raise JobTimeoutError(f"Job {job_id} still running", job_id)
            await asyncio.sleep(interval)
            try:
                _, state = await self._send("GET", url)
            except KloakdError as exc:
                gone = expired(exc, job_id)
                if gone is not None:
                    raise gone from exc
                raise
            result = outcome(state, job_id)
            if result is not None:
                return result
            interval = next_interval(interval)

    async def post(self, path: str, body: Optional[Dict[str, Any]] = None) -> Any:
        return await self.request("POST", path, json_body=body or {})

    async def put(self, path: str, body: Optional[Dict[str, Any]] = None) -> Any:
        return await self.request("PUT", path, json_body=body or {})

    async def patch(
        self,
        path: str,
        body: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Any:
        return await self.request("PATCH", path, json_body=body or {}, params=params)

    async def delete(self, path: str) -> None:
        await self.request("DELETE", path)

    async def aiter_sse(
        self,
        method: str,
        path: str,
        body: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> AsyncIterator[Tuple[str, Dict[str, Any]]]:
        """Open a Server-Sent Events stream; yields ``(event, data)`` pairs."""
        httpx = _httpx()
        headers = {**self._auth_headers(), "Accept": "text/event-stream"}
        kwargs: Dict[str, Any] = {"params": params, "headers": headers}
        if body is not None:
            kwargs["json"] = body
        client = self._http_client or httpx.AsyncClient(timeout=None)
        try:
            async with client.stream(method, self._url(path), **kwargs) as response:
                if response.status_code >= 400:
                    await response.aread()
                    raise_for_status(
                        response.status_code, response.content, None, response.headers
                    )
                event = ""
                async for line in response.aiter_lines():
                    line = line.strip()
                    if line.startswith("event:"):
                        event = line[6:].strip()
                    elif line.startswith("data:"):
                        data = line[5:].strip()
                        if not data:
                            continue
                        try:
                            yield event, json.loads(data)
                        except json.JSONDecodeError:
                            continue
        finally:
            if self._http_client is None:
                await client.aclose()
