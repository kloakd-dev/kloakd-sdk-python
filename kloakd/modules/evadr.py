"""
KLOAKD SDK — Evadr module namespace.

Evadr is KLOAKD's Anti-Bot Intelligence layer: it escalates through fetch
approaches until a page is served.

Usage::

    result = client.evadr.fetch("https://example.com")
    print(result.tier_used, result.vendor_detected)

    # Then pass the artifact downstream — no double-fetch
    data = client.kolektr.page("https://example.com", fetch_artifact_id=result.artifact_id)

The synchronous fetch answers within about 85 seconds (the API sits behind
Cloudflare, which closes requests at 100 s). A fetch still running then is
handed off as a job (HTTP 202); ``fetch`` follows it to its result.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, AsyncIterator, Dict, Iterator, List, Optional

from kloakd._handoff import DEFAULT_POLL_INTERVAL, DEFAULT_POLL_TIMEOUT, PollOptions
from kloakd.models import AnalyzeResult, FetchEvent, FetchResult
from kloakd.modules._ops import as_dict, as_list, seg

if TYPE_CHECKING:
    from kloakd._http import _AsyncHttpTransport, _HttpTransport


def _fetch_body(
    url: str,
    force_browser: bool,
    use_proxy: bool,
    session_artifact_id: Optional[str],
    webhook_url: Optional[str] = None,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {"url": url}
    if force_browser:
        body["force_browser"] = True
    if use_proxy:
        body["use_proxy"] = True
    if session_artifact_id:
        body["session_artifact_id"] = session_artifact_id
    if webhook_url:
        body["webhook_url"] = webhook_url
    return body


def _parse_fetch(raw: Dict[str, Any], url: str) -> FetchResult:
    artifact = raw.get("artifact")
    return FetchResult(
        success=bool(raw.get("success", False)),
        url=raw.get("url", url),
        status_code=int(raw.get("status_code") or 0),
        tier_used=int(raw.get("tier_used") or 1),
        html=raw.get("html"),
        vendor_detected=raw.get("vendor_detected"),
        anti_bot_bypassed=bool(raw.get("anti_bot_bypassed", False)),
        artifact_id=artifact.get("artifact_id")
        if isinstance(artifact, dict)
        else raw.get("artifact_id"),
        error=raw.get("error"),
        auth_required=bool(raw.get("auth_required", False)),
        discovery_id=raw.get("discovery_id"),
    )


def _analyze_body(
    url: str,
    status_code: int,
    headers: Optional[Dict[str, str]],
    body_snippet: Optional[str],
) -> Dict[str, Any]:
    return {
        "url": url,
        "status_code": status_code,
        "headers": headers or {},
        "body_snippet": body_snippet,
    }


def _parse_analyze(raw: Dict[str, Any]) -> AnalyzeResult:
    return AnalyzeResult(
        blocked=bool(raw.get("blocked", False)),
        vendor=raw.get("vendor"),
        confidence=float(raw.get("confidence") or 0.0),
        recommended_actions=raw.get("recommended_actions") or [],
    )


def _event(data: Dict[str, Any]) -> FetchEvent:
    """A pipeline event (``event_type``) or a job-state event (``type``)."""
    meta = data.get("metadata")
    return FetchEvent(
        type=str(data.get("event_type") or data.get("type") or ""),
        stage_id=data.get("stage_id"),
        status=data.get("status"),
        message=data.get("message"),
        progress_pct=data.get("progress_pct"),
        metadata=meta if isinstance(meta, dict) else {},
        error=data.get("error"),
        sequence=data.get("sequence"),
        job_id=data.get("job_id") or data.get("pipeline_id"),
        tier_used=data.get("tier_used"),
        artifact_id=data.get("artifact_id"),
    )


class EvadrNamespace:
    """Synchronous Evadr operations. Access via ``client.evadr``."""

    def __init__(self, transport: "_HttpTransport") -> None:
        self._t = transport

    def fetch(
        self,
        url: str,
        force_browser: bool = False,
        use_proxy: bool = False,
        session_artifact_id: Optional[str] = None,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        poll_timeout: float = DEFAULT_POLL_TIMEOUT,
    ) -> FetchResult:
        """
        Fetch a URL with automatic anti-bot bypass.

        A fetch the API hands off as a job (202, after ~85 s) is polled at
        its ``poll_url`` until it completes, first after ``poll_interval``
        seconds and then half as long again each time (up to 15 s), for at
        most ``poll_timeout`` seconds (then JobTimeoutError). A failed or
        expired job raises JobFailedError.
        """
        raw = self._t.post_following(
            "evadr/fetch",
            _fetch_body(url, force_browser, use_proxy, session_artifact_id),
            PollOptions(poll_interval, poll_timeout),
        )
        return _parse_fetch(raw, url)

    def fetch_async(
        self,
        url: str,
        force_browser: bool = False,
        use_proxy: bool = False,
        webhook_url: Optional[str] = None,
        session_artifact_id: Optional[str] = None,
    ) -> str:
        """Start a fetch as a job; returns the job id (poll with get_job or wait_for_job)."""
        raw = self._t.post(
            "evadr/fetch/async",
            _fetch_body(
                url, force_browser, use_proxy, session_artifact_id, webhook_url
            ),
        )
        return str(raw["job_id"])

    def wait_for_job(
        self,
        job_id: str,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        timeout: float = DEFAULT_POLL_TIMEOUT,
    ) -> Dict[str, Any]:
        """Poll a fetch job until it completes (its result) or fails (JobFailedError)."""
        return self._t.follow(
            job_id,
            self._t._url(f"evadr/jobs/{seg(job_id)}"),
            PollOptions(poll_interval, timeout),
        )

    def fetch_stream(
        self, url: str, force_browser: bool = False
    ) -> Iterator[FetchEvent]:
        """Start a fetch as a job and yield its progress events."""
        job_id = self.fetch_async(url, force_browser=force_browser)
        for data in self.job_events(job_id):
            yield _event(data)

    def analyze(
        self,
        url: str,
        status_code: int = 200,
        headers: Optional[Dict[str, str]] = None,
        body_snippet: Optional[str] = None,
    ) -> AnalyzeResult:
        """Predict the anti-bot vendor from a response you already have, without fetching."""
        return _parse_analyze(
            self._t.post(
                "evadr/analyze", _analyze_body(url, status_code, headers, body_snippet)
            )
        )

    def scan(self, url: str) -> Dict[str, Any]:
        """Lightweight HTTP fetch and anti-bot analysis of a URL."""
        return as_dict(self._t.post("evadr/scan", {"url": url}))

    def profile(self, url: str) -> Dict[str, Any]:
        """The canonical site profile of a URL."""
        return as_dict(self._t.post("evadr/profile", {"url": url}))

    def get_job(self, job_id: str) -> Dict[str, Any]:
        """A fetch job's state: status, and result or error when finished."""
        return as_dict(self._t.get(f"evadr/jobs/{seg(job_id)}"))

    def job_events(self, job_id: str) -> Iterator[Dict[str, Any]]:
        """A fetch job's progress events (Server-Sent Events)."""
        for _event_name, data in self._t.iter_sse("GET", f"evadr/jobs/{seg(job_id)}/events"):
            yield data

    def list_vendors(self) -> List[Dict[str, Any]]:
        """All anti-bot vendors Evadr detects."""
        return as_list(self._t.get("evadr/vendors"))

    def list_proxies(self) -> List[Dict[str, Any]]:
        """Stored proxy configurations (names and masked URLs only)."""
        return as_list(self._t.get("evadr/proxies"))

    def store_proxy(self, name: str, proxy_url: str) -> None:
        """Store an encrypted proxy configuration for later fetches."""
        self._t.post("evadr/proxies", {"name": name, "proxy_url": proxy_url})

    def delete_proxy(self, name: str) -> None:
        """Delete a stored proxy configuration."""
        self._t.delete(f"evadr/proxies/{seg(name)}")


class AsyncEvadrNamespace:
    """Async Evadr operations. Access via ``async_client.evadr``."""

    def __init__(self, transport: "_AsyncHttpTransport") -> None:
        self._t = transport

    async def fetch(
        self,
        url: str,
        force_browser: bool = False,
        use_proxy: bool = False,
        session_artifact_id: Optional[str] = None,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        poll_timeout: float = DEFAULT_POLL_TIMEOUT,
    ) -> FetchResult:
        """Async equivalent of EvadrNamespace.fetch (follows a 202 hand-off)."""
        raw = await self._t.post_following(
            "evadr/fetch",
            _fetch_body(url, force_browser, use_proxy, session_artifact_id),
            PollOptions(poll_interval, poll_timeout),
        )
        return _parse_fetch(raw, url)

    async def fetch_async(
        self,
        url: str,
        force_browser: bool = False,
        use_proxy: bool = False,
        webhook_url: Optional[str] = None,
        session_artifact_id: Optional[str] = None,
    ) -> str:
        """Async equivalent of EvadrNamespace.fetch_async."""
        raw = await self._t.post(
            "evadr/fetch/async",
            _fetch_body(
                url, force_browser, use_proxy, session_artifact_id, webhook_url
            ),
        )
        return str(raw["job_id"])

    async def wait_for_job(
        self,
        job_id: str,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        timeout: float = DEFAULT_POLL_TIMEOUT,
    ) -> Dict[str, Any]:
        """Async equivalent of EvadrNamespace.wait_for_job."""
        return await self._t.follow(
            job_id,
            self._t._url(f"evadr/jobs/{seg(job_id)}"),
            PollOptions(poll_interval, timeout),
        )

    async def fetch_stream(
        self, url: str, force_browser: bool = False
    ) -> AsyncIterator[FetchEvent]:
        """Start a fetch as a job and yield its progress events."""
        job_id = await self.fetch_async(url, force_browser=force_browser)
        async for data in self.job_events(job_id):
            yield _event(data)

    async def analyze(
        self,
        url: str,
        status_code: int = 200,
        headers: Optional[Dict[str, str]] = None,
        body_snippet: Optional[str] = None,
    ) -> AnalyzeResult:
        """Async equivalent of EvadrNamespace.analyze."""
        return _parse_analyze(
            await self._t.post(
                "evadr/analyze", _analyze_body(url, status_code, headers, body_snippet)
            )
        )

    async def scan(self, url: str) -> Dict[str, Any]:
        """Async equivalent of EvadrNamespace.scan."""
        return as_dict(await self._t.post("evadr/scan", {"url": url}))

    async def profile(self, url: str) -> Dict[str, Any]:
        """Async equivalent of EvadrNamespace.profile."""
        return as_dict(await self._t.post("evadr/profile", {"url": url}))

    async def get_job(self, job_id: str) -> Dict[str, Any]:
        """Async equivalent of EvadrNamespace.get_job."""
        return as_dict(await self._t.get(f"evadr/jobs/{seg(job_id)}"))

    async def job_events(self, job_id: str) -> AsyncIterator[Dict[str, Any]]:
        """Async equivalent of EvadrNamespace.job_events."""
        async for _event_name, data in self._t.aiter_sse(
            "GET", f"evadr/jobs/{seg(job_id)}/events"
        ):
            yield data

    async def list_vendors(self) -> List[Dict[str, Any]]:
        return as_list(await self._t.get("evadr/vendors"))

    async def list_proxies(self) -> List[Dict[str, Any]]:
        return as_list(await self._t.get("evadr/proxies"))

    async def store_proxy(self, name: str, proxy_url: str) -> None:
        await self._t.post("evadr/proxies", {"name": name, "proxy_url": proxy_url})

    async def delete_proxy(self, name: str) -> None:
        await self._t.delete(f"evadr/proxies/{seg(name)}")
