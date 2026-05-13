"""
KLOAKD SDK — Evadr module namespace.

Evadr is KLOAKD's Anti-Bot Intelligence layer. It transparently escalates
through fetch tiers (HTTP → stealth browser → proxy → RPA) until it succeeds
or exhausts all options.

Usage::

    result = client.evadr.fetch("https://example.com")
    print(result.tier_used, result.vendor_detected)

    # Then pass the artifact downstream — no double-fetch
    data = client.kolektr.page(
        "https://example.com",
        fetch_artifact_id=result.artifact_id,
    )
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, AsyncIterator, Dict, Optional

from kloakd.models import AnalyzeResult, FetchEvent, FetchResult

if TYPE_CHECKING:
    from kloakd._http import _AsyncHttpTransport, _HttpTransport


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
    ) -> FetchResult:
        """
        Fetch a URL with automatic anti-bot bypass.

        Escalates through fetch tiers (HTTP → stealth browser → proxy → RPA)
        until it succeeds. Returns the HTML and a FETCHED_CONTENT artifact_id
        that downstream modules (Kolektr, Webgrph) can reuse.

        Args:
            url: Target URL.
            force_browser: Skip Tier 1 HTTP, go straight to browser.
            use_proxy: Route through a configured proxy.
            session_artifact_id: AUTHENTICATED_SESSION artifact from Fetchyr.

        Returns:
            FetchResult with html, tier_used, and artifact_id.
        """
        body: Dict[str, Any] = {"url": url}
        if force_browser:
            body["force_browser"] = True
        if use_proxy:
            body["use_proxy"] = True
        if session_artifact_id:
            body["session_artifact_id"] = session_artifact_id

        raw = self._t.post("evadr/fetch", body)
        return FetchResult(
            success=raw.get("success", False),
            url=raw.get("url", url),
            status_code=raw.get("status_code", 0),
            tier_used=raw.get("tier_used", 1),
            html=raw.get("html"),
            vendor_detected=raw.get("vendor_detected"),
            anti_bot_bypassed=raw.get("anti_bot_bypassed", False),
            artifact_id=raw.get("artifact_id"),
            error=raw.get("error"),
        )

    def fetch_async(
        self,
        url: str,
        force_browser: bool = False,
        use_proxy: bool = False,
        webhook_url: Optional[str] = None,
    ) -> str:
        """
        Enqueue an async fetch job and return a job_id for polling.

        Args:
            url: Target URL.
            force_browser: Skip Tier 1 HTTP.
            use_proxy: Route through a configured proxy.
            webhook_url: URL to POST the result to on completion.

        Returns:
            job_id string.
        """
        body: Dict[str, Any] = {"url": url, "async": True}
        if force_browser:
            body["force_browser"] = True
        if use_proxy:
            body["use_proxy"] = True
        if webhook_url:
            body["webhook_url"] = webhook_url

        raw = self._t.post("evadr/fetch", body)
        return str(raw["job_id"])

    def analyze(
        self,
        url: str,
        status_code: int = 200,
        headers: Optional[Dict[str, str]] = None,
        body_snippet: Optional[str] = None,
    ) -> AnalyzeResult:
        """
        Predict anti-bot vendor from an HTTP response without re-fetching.

        Args:
            url: Target URL (for metadata).
            status_code: HTTP status code received.
            headers: Response headers dict.
            body_snippet: First 1000 chars of response body.

        Returns:
            AnalyzeResult with blocked, vendor, confidence, recommended_actions.
        """
        raw = self._t.post("evadr/analyze", {
            "url": url,
            "status_code": status_code,
            "headers": headers or {},
            "body_snippet": body_snippet,
        })
        return AnalyzeResult(
            blocked=raw.get("blocked", False),
            vendor=raw.get("vendor"),
            confidence=raw.get("confidence", 0.0),
            recommended_actions=raw.get("recommended_actions", []),
        )

    def scan(
        self,
        url: str,
        status_code: int = 200,
        headers: Optional[Dict[str, str]] = None,
        body_snippet: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Scan a URL response for anti-bot vendor signatures.

        Args:
            url: Target URL.
            status_code: HTTP status code received.
            headers: Response headers dict.
            body_snippet: First 1000 chars of response body.

        Returns:
            Dict with vendor detection results.
        """
        body: Dict[str, Any] = {"url": url, "status_code": status_code}
        if headers:
            body["headers"] = headers
        if body_snippet:
            body["body_snippet"] = body_snippet
        return self._t.post("evadr/scan", body)

    def get_job(self, job_id: str) -> Dict[str, Any]:
        """Poll an async fetch job by ID."""
        return self._t.get(f"evadr/jobs/{job_id}")

    def get_job_events(self, job_id: str) -> Dict[str, Any]:
        """Retrieve SSE events for an async fetch job."""
        return self._t.get(f"evadr/jobs/{job_id}/events")

    def list_vendors(self) -> Dict[str, Any]:
        """List all known anti-bot detection vendors."""
        return self._t.get("evadr/vendors")

    def list_profiles(self) -> Dict[str, Any]:
        """List available evasion profiles."""
        return self._t.get("evadr/profiles")

    def list_proxies(self) -> Dict[str, Any]:
        """List stored proxy configurations (names only, no secrets)."""
        return self._t.get("evadr/proxies")

    def store_proxy(self, name: str, proxy_url: str) -> None:
        """Store an encrypted proxy configuration for use in future fetch calls."""
        self._t.post("evadr/proxies", {"name": name, "proxy_url": proxy_url})

    def delete_proxy(self, name: str) -> None:
        """Delete a stored proxy configuration by name."""
        self._t.delete(f"evadr/proxies/{name}")


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
    ) -> FetchResult:
        """Async equivalent of EvadrNamespace.fetch."""
        body: Dict[str, Any] = {"url": url}
        if force_browser:
            body["force_browser"] = True
        if use_proxy:
            body["use_proxy"] = True
        if session_artifact_id:
            body["session_artifact_id"] = session_artifact_id

        raw = await self._t.post("evadr/fetch", body)
        return FetchResult(
            success=raw.get("success", False),
            url=raw.get("url", url),
            status_code=raw.get("status_code", 0),
            tier_used=raw.get("tier_used", 1),
            html=raw.get("html"),
            vendor_detected=raw.get("vendor_detected"),
            anti_bot_bypassed=raw.get("anti_bot_bypassed", False),
            artifact_id=raw.get("artifact_id"),
            error=raw.get("error"),
        )

    @asynccontextmanager
    async def fetch_stream(
        self,
        url: str,
        force_browser: bool = False,
    ) -> AsyncIterator[AsyncIterator[FetchEvent]]:
        """
        Async SSE event stream for a fetch operation.

        Usage::

            async with client.evadr.fetch_stream("https://example.com") as events:
                async for event in events:
                    print(event.type, event.tier, event.vendor)
        """
        import json as _json

        try:
            import httpx
        except ImportError as exc:
            raise RuntimeError("httpx is required for fetch_stream") from exc

        url_path = self._t._url("evadr/fetch/stream")
        headers = self._t._auth_headers()
        headers["Accept"] = "text/event-stream"
        body: Dict[str, Any] = {"url": url}
        if force_browser:
            body["force_browser"] = True

        async with httpx.AsyncClient(timeout=None) as http:
            async with http.stream("POST", url_path, json=body, headers=headers) as response:
                from kloakd._http import _HttpTransport
                _HttpTransport._raise_for_status(response.status_code, b"")

                async def _event_iter() -> AsyncIterator[FetchEvent]:
                    async for line in response.aiter_lines():
                        line = line.strip()
                        if not line.startswith("data:"):
                            continue
                        data_str = line[5:].strip()
                        if not data_str:
                            continue
                        try:
                            data = _json.loads(data_str)
                            yield FetchEvent(
                                type=data.get("type", ""),
                                tier=data.get("tier"),
                                vendor=data.get("vendor"),
                                metadata=data.get("metadata", {}),
                            )
                        except _json.JSONDecodeError:
                            continue

                yield _event_iter()

    async def analyze(
        self,
        url: str,
        status_code: int = 200,
        headers: Optional[Dict[str, str]] = None,
        body_snippet: Optional[str] = None,
    ) -> AnalyzeResult:
        """Async equivalent of EvadrNamespace.analyze."""
        raw = await self._t.post("evadr/analyze", {
            "url": url,
            "status_code": status_code,
            "headers": headers or {},
            "body_snippet": body_snippet,
        })
        return AnalyzeResult(
            blocked=raw.get("blocked", False),
            vendor=raw.get("vendor"),
            confidence=raw.get("confidence", 0.0),
            recommended_actions=raw.get("recommended_actions", []),
        )

    async def scan(
        self,
        url: str,
        status_code: int = 200,
        headers: Optional[Dict[str, str]] = None,
        body_snippet: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Async equivalent of EvadrNamespace.scan."""
        body: Dict[str, Any] = {"url": url, "status_code": status_code}
        if headers:
            body["headers"] = headers
        if body_snippet:
            body["body_snippet"] = body_snippet
        return await self._t.post("evadr/scan", body)

    async def get_job(self, job_id: str) -> Dict[str, Any]:
        """Async equivalent of EvadrNamespace.get_job."""
        return await self._t.get(f"evadr/jobs/{job_id}")

    async def get_job_events(self, job_id: str) -> Dict[str, Any]:
        """Async equivalent of EvadrNamespace.get_job_events."""
        return await self._t.get(f"evadr/jobs/{job_id}/events")

    async def list_vendors(self) -> Dict[str, Any]:
        """Async equivalent of EvadrNamespace.list_vendors."""
        return await self._t.get("evadr/vendors")

    async def list_profiles(self) -> Dict[str, Any]:
        """Async equivalent of EvadrNamespace.list_profiles."""
        return await self._t.get("evadr/profiles")

    async def list_proxies(self) -> Dict[str, Any]:
        """Async equivalent of EvadrNamespace.list_proxies."""
        return await self._t.get("evadr/proxies")

    async def store_proxy(self, name: str, proxy_url: str) -> None:
        """Async equivalent of EvadrNamespace.store_proxy."""
        await self._t.post("evadr/proxies", {"name": name, "proxy_url": proxy_url})

    async def delete_proxy(self, name: str) -> None:
        """Async equivalent of EvadrNamespace.delete_proxy."""
        await self._t.delete(f"evadr/proxies/{name}")
