"""
KLOAKD SDK — Shared HTTP transport layer.

Provides the _HttpTransport class used by Kloakd (sync) and _AsyncHttpTransport
used by AsyncKloakd. All retry logic, error mapping, header construction and
Server-Sent Events parsing live here — once, not once per namespace.

Retry policy:
    - 429 ``rate_limited``: any method, after Retry-After (header, else the
      body's ``retry_after``, else until ``reset_at``). The playground quota
      (``retry_after`` 0 and no ``reset_at``, kobe-scraper
      kernel/gateway/rate_limiter.py) does not reset and is not retried.
    - 503 ``billing_unavailable``: any method (nothing was started), after
      Retry-After.
    - Other 5xx and network errors: GET, HEAD and DELETE only. A POST, PUT
      or PATCH may have done its work, so it is never repeated.
    - Never: 400, 401, 402, 403, 404, 409, 422, 429 ``gb_exhausted``.
    - Otherwise exponential backoff (1s * 2^attempt); every wait capped at 60s.
    - Attempts: ``max_retries`` (default 3).
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, Iterator, Mapping, Optional, Tuple, Type

from kloakd._handoff import PollOptions, expired, is_handoff, next_interval, outcome
from kloakd.errors import (
    ApiError,
    AuthenticationError,
    BillingUnavailableError,
    ConcurrencyLimitError,
    ForbiddenError,
    JobTimeoutError,
    KloakdError,
    NotEntitledError,
    PaymentRequiredError,
    QuotaExceededError,
    RateLimitError,
    UpstreamError,
)
from kloakd.modules._ops import seg

logger = logging.getLogger("kloakd.http")

_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
_IDEMPOTENT_METHODS = {"GET", "HEAD", "DELETE"}
_SDK_VERSION = "0.5.0"
_MAX_WAIT = 60.0


def _sdk_header(language: str = "python") -> str:
    return f"{language}/{_SDK_VERSION}"


def _user_agent() -> str:
    return f"kloakd-sdk-python/{_SDK_VERSION}"


def _httpx() -> Any:
    try:
        import httpx
    except ImportError as exc:  # pragma: no cover - httpx is a dependency
        raise RuntimeError("httpx is required: pip install kloakd-sdk") from exc
    return httpx


def _decode(content: Any) -> Any:
    """A response body: parsed JSON, else its text (a proxy's HTML error page,
    a plain-text route), else an empty object when there is no body."""
    if not content:
        return {}
    try:
        return json.loads(content)
    except (ValueError, TypeError):
        if isinstance(content, (bytes, bytearray)):
            return bytes(content).decode("utf-8", errors="replace")
        return str(content)


def _validation_message(items: Any) -> str:
    """The messages of a 422 ``detail`` list (``[{loc, msg, type}, ...]``)."""
    parts = []
    for item in items:
        if isinstance(item, dict):
            loc = ".".join(str(x) for x in item.get("loc") or [] if x != "body")
            msg = str(item.get("msg") or item.get("message") or item)
            parts.append(f"{loc}: {msg}" if loc else msg)
        else:
            parts.append(str(item))
    return "; ".join(parts)


def _seconds_until(reset_at: str) -> Optional[float]:
    """Seconds from now until an ISO 8601 ``reset_at`` (None if unparseable)."""
    try:
        when = datetime.fromisoformat(reset_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())


def _int_or_none(value: Any) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def raise_for_status(
    status_code: int,
    content: Any = b"",
    body: Optional[Dict[str, Any]] = None,
    headers: Optional[Mapping[str, str]] = None,
) -> None:
    """Map a non-2xx response to the matching KloakdError subclass, with the
    API's error code (``detail.error``) on ``code``.

    The API puts its error in ``detail``: a string, an object
    ``{"error": ..., "message": ...}`` or (422) a list of validation errors.
    All three are read. A body that is not JSON becomes the message.
    """
    if status_code < 400:
        return
    raise _error_for(status_code, content, body, headers)


def _error_for(
    status_code: int,
    content: Any = b"",
    body: Optional[Dict[str, Any]] = None,
    headers: Optional[Mapping[str, str]] = None,
) -> KloakdError:
    """The error for a non-2xx response; its ``code`` is the API's error code."""
    exc = _mapped(status_code, content, body, headers)
    if exc.code is None:
        exc.code = _code_of(content, body) or None
    return exc


def _code_of(content: Any, body: Optional[Dict[str, Any]]) -> str:
    if body is None:
        decoded = _decode(content)
        body = decoded if isinstance(decoded, dict) else {}
    detail = body.get("detail")
    return str((detail if isinstance(detail, dict) else body).get("error") or "")


def _mapped(
    status_code: int,
    content: Any,
    body: Optional[Dict[str, Any]],
    headers: Optional[Mapping[str, str]],
) -> KloakdError:
    text = ""
    if body is None:
        decoded = _decode(content)
        if isinstance(decoded, dict):
            body = decoded
        else:
            text = str(decoded)
            body = {}
    raw_detail = body.get("detail")
    detail_obj: Dict[str, Any] = raw_detail if isinstance(raw_detail, dict) else body
    code = str(detail_obj.get("error") or "")
    if isinstance(raw_detail, str):
        detail = raw_detail
    elif isinstance(raw_detail, list):
        detail = _validation_message(raw_detail)
    else:
        detail = (
            detail_obj.get("message")
            or body.get("message")
            or code
            or text.strip()[:500]
            or f"HTTP {status_code}"
        )
    retry_header: Optional[float] = None
    if headers is not None:
        value = headers.get("retry-after") or headers.get("Retry-After")
        try:
            retry_header = float(value) if value is not None else None
        except ValueError:
            retry_header = None

    if status_code == 401:
        return AuthenticationError(f"Invalid or expired API key: {detail}")
    if status_code == 402:
        return PaymentRequiredError(
            str(detail),
            upgrade_url=detail_obj.get(
                "upgrade_url", "https://app.kloakd.dev/settings/billing"
            ),
        )
    if status_code == 403:
        if code == "tier_access_denied":
            # billing/tier_policy.py TierAccessDenied.to_dict()
            feature = detail_obj.get("feature")
            return NotEntitledError(
                message=f"Not available on your plan: {detail}",
                module=str(feature or "unknown"),
                upgrade_url=detail_obj.get(
                    "upgrade_url", "https://app.kloakd.dev/billing"
                ),
                code=code,
                feature=feature,
                current_tier=detail_obj.get("current_tier"),
                required_tier=detail_obj.get("required_tier"),
            )
        if code == "not_entitled":
            return NotEntitledError(
                message=f"Not entitled to this module: {detail}",
                module=detail_obj.get("module", "unknown"),
                upgrade_url=detail_obj.get(
                    "upgrade_url", "https://app.kloakd.dev/billing"
                ),
                code=code,
            )
        return ForbiddenError(f"Forbidden: {detail}", code=code or None)
    if status_code == 409 and code == "concurrent_limit":
        # kernel/gateway/dependencies.py check_concurrent_quota
        return ConcurrencyLimitError(
            str(detail),
            concurrent_limit=_int_or_none(detail_obj.get("concurrent_limit")),
            active_crawls=_int_or_none(detail_obj.get("active_crawls")),
            tier=detail_obj.get("tier"),
        )
    if status_code == 429:
        if code == "gb_exhausted":
            return QuotaExceededError(
                str(detail),
                tier=str(detail_obj.get("tier", "")),
                upgrade_url=detail_obj.get(
                    "upgrade_url", "https://app.kloakd.dev/settings/billing"
                ),
            )
        reset_at = str(detail_obj.get("reset_at") or "")
        retry_after: Optional[float] = retry_header
        if retry_after is None and detail_obj.get("retry_after") is not None:
            try:
                retry_after = float(detail_obj["retry_after"])
            except (TypeError, ValueError):
                retry_after = None
        if (retry_after is None or retry_after <= 0) and reset_at:
            retry_after = _seconds_until(reset_at)
        if retry_after is None:
            retry_after = 0.0 if "retry_after" in detail_obj else 60.0
        return RateLimitError(
            message=f"Rate limit exceeded: {detail}",
            retry_after=int(retry_after + 0.999),
            reset_at=reset_at,
            quota_used=_int_or_none(detail_obj.get("quota_used")),
            quota_limit=_int_or_none(detail_obj.get("quota_limit")),
            upgrade_url=detail_obj.get("upgrade_url"),
        )
    if status_code == 502:
        return UpstreamError(f"Upstream fetch failed: {detail}")
    if status_code == 503 and code == "billing_unavailable":
        return BillingUnavailableError(
            str(detail), retry_after=retry_header if retry_header is not None else 30.0
        )
    return ApiError(f"KLOAKD API error {status_code}: {detail}", status_code)


def _is_retryable(exc: KloakdError, method: str = "GET") -> bool:
    """Whether a request that raised ``exc`` may be sent again."""
    if isinstance(exc, (QuotaExceededError, PaymentRequiredError)):
        return False
    if isinstance(exc, RateLimitError):
        return not exc.quota_exhausted
    if isinstance(exc, BillingUnavailableError):
        return True
    if exc.status_code not in _RETRYABLE_STATUS_CODES:
        return False
    return method.upper() in _IDEMPOTENT_METHODS


def _backoff(attempt: int, exc: Optional[KloakdError]) -> float:
    if isinstance(exc, RateLimitError) and exc.retry_after >= 0:
        return min(float(exc.retry_after), _MAX_WAIT)
    if isinstance(exc, BillingUnavailableError) and exc.retry_after >= 0:
        return min(float(exc.retry_after), _MAX_WAIT)
    return min(float(2.0**attempt), _MAX_WAIT)


def _parse_sse_line(line: str, event: str) -> Tuple[str, Optional[Dict[str, Any]]]:
    """One SSE line: the current event name, and its data when it is a data line.
    A blank line ends a message, so the event name resets."""
    line = line.strip()
    if not line:
        return "", None
    if line.startswith("event:"):
        return line[6:].strip(), None
    if line.startswith("data:"):
        data = line[5:].strip()
        if data:
            try:
                parsed = json.loads(data)
            except json.JSONDecodeError:
                return event, None
            return event, parsed if isinstance(parsed, dict) else {"value": parsed}
    return event, None


def _parse_sse_lines(lines: Iterator[str]) -> Iterator[Tuple[str, Dict[str, Any]]]:
    event = ""
    for line in lines:
        event, data = _parse_sse_line(line, event)
        if data is not None:
            yield event, data


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
            "User-Agent": _user_agent(),
            "Content-Type": "application/json",
        }

    def _org_prefix(self) -> str:
        return f"/api/v1/organizations/{seg(self._organization_id)}"

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

    def _handoff_url(self, job_id: str) -> str:
        """``GET /api/v1/organizations/{org}/handoff/{job_id}``
        (kobe-scraper kernel/sync_handoff.py poll_handoff)."""
        return self._url(f"handoff/{seg(job_id)}")

    def _retry_wait(
        self, method: str, attempt: int, exc: Exception
    ) -> Optional[float]:
        """Seconds to wait before sending again, or None to raise ``exc``."""
        if attempt + 1 >= self._max_retries:
            return None
        if isinstance(exc, KloakdError):
            if not _is_retryable(exc, method):
                return None
            return _backoff(attempt, exc)
        # A network error or timeout: the request may have reached the API.
        if method.upper() not in _IDEMPOTENT_METHODS:
            return None
        return _backoff(attempt, None)

    def _retryable_errors(self) -> Tuple[Type[Exception], ...]:
        httpx = _httpx()
        return (KloakdError, httpx.TransportError)

    @staticmethod
    def _checked(response: Any, raw: bool) -> Tuple[int, Any]:
        """(status, body) of a response, raising for an error status."""
        content = response.content
        body = _decode(content)
        raise_for_status(
            response.status_code,
            content,
            body if isinstance(body, dict) else None,
            response.headers,
        )
        return response.status_code, (content if raw else body)

    # Kept for callers of the 0.2 static API.
    _raise_for_status = staticmethod(raise_for_status)
    _is_retryable = staticmethod(_is_retryable)
    _backoff = staticmethod(_backoff)


def _log_retry(prefix: str, attempt: int, total: int, wait: float, exc: Exception) -> None:
    logger.warning(
        "%s failed (attempt %d/%d), retrying in %.1fs: %s",
        prefix,
        attempt + 1,
        total,
        wait,
        exc.message if isinstance(exc, KloakdError) else repr(exc),
    )


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
        """Execute a synchronous HTTP request with retry logic; returns the
        parsed JSON (or the text of a non-JSON body)."""
        return self._send(method, self._url(path), json_body, params)[1]

    def request_bytes(
        self,
        method: str,
        path: str,
        json_body: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> bytes:
        """As ``request``, returning the raw body (a file download)."""
        return bytes(self._send(method, self._url(path), json_body, params, raw=True)[1])

    def _send(
        self,
        method: str,
        url: str,
        json_body: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        raw: bool = False,
    ) -> Tuple[int, Any]:
        """One request to ``url`` with retries; returns (status code, body)."""
        httpx = _httpx()
        headers = self._auth_headers()
        network_errors = self._retryable_errors()

        attempt = 0
        while True:
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
                return self._checked(response, raw)
            except network_errors as exc:
                wait = self._retry_wait(method, attempt, exc)
                if wait is None:
                    raise
                _log_retry("Request", attempt, self._max_retries, wait, exc)
                time.sleep(wait)
                attempt += 1

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
        """Execute an async HTTP request with retry logic; returns the parsed
        JSON (or the text of a non-JSON body)."""
        return (await self._send(method, self._url(path), json_body, params))[1]

    async def request_bytes(
        self,
        method: str,
        path: str,
        json_body: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> bytes:
        """As ``request``, returning the raw body (a file download)."""
        _, content = await self._send(
            method, self._url(path), json_body, params, raw=True
        )
        return bytes(content)

    async def _send(
        self,
        method: str,
        url: str,
        json_body: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        raw: bool = False,
    ) -> Tuple[int, Any]:
        """One request to ``url`` with retries; returns (status code, body)."""
        import asyncio

        httpx = _httpx()
        headers = self._auth_headers()
        network_errors = self._retryable_errors()

        attempt = 0
        while True:
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
                return self._checked(response, raw)
            except network_errors as exc:
                wait = self._retry_wait(method, attempt, exc)
                if wait is None:
                    raise
                _log_retry("Async request", attempt, self._max_retries, wait, exc)
                await asyncio.sleep(wait)
                attempt += 1

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
                    event, data = _parse_sse_line(line, event)
                    if data is not None:
                        yield event, data
        finally:
            if self._http_client is None:
                await client.aclose()
