"""
KLOAKD SDK — Webgrph module namespace.

Webgrph builds a complete SITE_HIERARCHY artifact via BFS crawl. The artifact
can be seeded into Skanyr for API discovery or inspected directly.

Usage::

    crawl = client.webgrph.crawl("https://example.com", max_depth=3)
    print(f"Found {crawl.total_pages} pages")

    # Seed into Skanyr
    apis = client.skanyr.discover(
        "https://example.com",
        site_hierarchy_artifact_id=crawl.artifact_id,
    )
"""

from __future__ import annotations

import json as _json
import time
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, AsyncIterator, Dict, List, Optional

from kloakd.models import CrawlEvent, CrawlResult, PageNode

if TYPE_CHECKING:
    from kloakd._http import _AsyncHttpTransport, _HttpTransport

_DEFAULT_POLL_TIMEOUT = 300.0
_DEFAULT_POLL_INTERVAL = 2.0


def _parse_crawl(raw: Dict[str, Any], url: str, limit: int) -> CrawlResult:
    pages = [
        PageNode(
            url=p.get("url", ""),
            depth=p.get("depth", 0),
            title=p.get("title"),
            status_code=p.get("status_code"),
            children=p.get("children", []),
        )
        for p in raw.get("pages", [])
    ]
    total = raw.get("total", raw.get("total_pages", 0))
    artifact = raw.get("artifact")
    return CrawlResult(
        success=raw.get("success", False),
        crawl_id=raw.get("crawl_id", ""),
        url=raw.get("url", url),
        total_pages=raw.get("total_pages", len(pages)),
        max_depth_reached=raw.get("max_depth_reached", 0),
        pages=pages,
        artifact_id=artifact.get("artifact_id") if artifact else raw.get("artifact_id"),
        has_more=raw.get("has_more", False),
        total=total,
        error=raw.get("error"),
    )


def _poll_crawl_status_sync(
    transport: "_HttpTransport",
    crawl_id: str,
    timeout: float,
    interval: float,
) -> Optional[Dict[str, Any]]:
    """Poll crawl status until terminal state or timeout (sync)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = transport.get(f"webgrph/crawl/{crawl_id}")
        state = status.get("status", "pending")
        if state in ("completed", "failed", "cancelled"):
            return status
        time.sleep(interval)
    return None


async def _poll_crawl_status_async(
    transport: "_AsyncHttpTransport",
    crawl_id: str,
    timeout: float,
    interval: float,
) -> Optional[Dict[str, Any]]:
    """Poll crawl status until terminal state or timeout (async)."""
    import asyncio

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = await transport.get(f"webgrph/crawl/{crawl_id}")
        state = status.get("status", "pending")
        if state in ("completed", "failed", "cancelled"):
            return status
        await asyncio.sleep(interval)
    return None


class WebgrphNamespace:
    """Synchronous Webgrph operations. Access via ``client.webgrph``."""

    def __init__(self, transport: "_HttpTransport") -> None:
        self._t = transport

    def crawl(
        self,
        url: str,
        max_depth: int = 3,
        max_pages: int = 100,
        include_external_links: bool = False,
        session_artifact_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        poll_timeout: float = _DEFAULT_POLL_TIMEOUT,
        poll_interval: float = _DEFAULT_POLL_INTERVAL,
    ) -> CrawlResult:
        """
        Crawl a site and produce a SITE_HIERARCHY artifact.

        The backend returns 202 immediately with a ``crawl_id`` and runs the
        crawl asynchronously in a Celery worker. This method polls
        ``get_crawl_status()`` until the crawl completes (or fails), then
        fetches the discovered pages via ``get_crawl_pages()``.

        Args:
            url: Seed URL.
            max_depth: Maximum BFS depth. Default 3.
            max_pages: Maximum pages to crawl. Default 100.
            include_external_links: Follow off-domain links.
            session_artifact_id: AUTHENTICATED_SESSION artifact from Fetchyr.
            limit: Max pages in this response (pagination). Default 100.
            offset: Pagination offset. Default 0.
            poll_timeout: Max seconds to wait for crawl completion. Default 300.
            poll_interval: Seconds between status polls. Default 2.

        Returns:
            CrawlResult with pages list and artifact_id.
        """
        body: Dict[str, Any] = {
            "url": url,
            "max_depth": max_depth,
            "max_pages": max_pages,
            "include_external_links": include_external_links,
            "limit": limit,
            "offset": offset,
        }
        if session_artifact_id:
            body["session_artifact_id"] = session_artifact_id

        raw = self._t.post("webgrph/crawl", body)
        crawl_id = raw.get("crawl_id", "")
        if not crawl_id:
            return _parse_crawl(raw, url, limit)

        final_status = _poll_crawl_status_sync(
            self._t, crawl_id, poll_timeout, poll_interval
        )
        if final_status is None:
            return CrawlResult(
                success=False,
                crawl_id=crawl_id,
                url=url,
                total_pages=0,
                max_depth_reached=0,
                error=f"Crawl timed out after {poll_timeout}s",
            )

        if final_status.get("status") == "failed":
            return CrawlResult(
                success=False,
                crawl_id=crawl_id,
                url=url,
                total_pages=0,
                max_depth_reached=0,
                error=final_status.get("error", "Crawl failed"),
            )

        pages_raw = self._t.get(f"webgrph/crawl/{crawl_id}/pages")
        pages = [
            PageNode(
                url=p.get("url", ""),
                depth=p.get("depth", 0),
                title=(p.get("metadata") or {}).get("title") or p.get("title"),
                status_code=p.get("status_code"),
                children=p.get("children_urls", p.get("children", [])),
            )
            for p in pages_raw.get("nodes", [])
        ]
        return CrawlResult(
            success=True,
            crawl_id=crawl_id,
            url=url,
            total_pages=pages_raw.get("total", len(pages)),
            max_depth_reached=final_status.get("max_depth_reached", 0),
            pages=pages,
            artifact_id=final_status.get("artifact_id"),
            has_more=pages_raw.get("next_cursor") is not None,
            total=pages_raw.get("total", len(pages)),
            next_cursor=pages_raw.get("next_cursor"),
            error=None,
        )

    def crawl_all(
        self,
        url: str,
        max_depth: int = 3,
        max_pages: int = 1000,
        include_external_links: bool = False,
        session_artifact_id: Optional[str] = None,
        poll_timeout: float = _DEFAULT_POLL_TIMEOUT,
        poll_interval: float = _DEFAULT_POLL_INTERVAL,
    ) -> List[PageNode]:
        """
        Auto-paginate crawl results, returning all discovered pages.

        Returns:
            Complete list of PageNode objects.
        """
        all_pages: List[PageNode] = []
        result = self.crawl(
            url,
            max_depth=max_depth,
            max_pages=max_pages,
            include_external_links=include_external_links,
            session_artifact_id=session_artifact_id,
            limit=100,
            offset=0,
            poll_timeout=poll_timeout,
            poll_interval=poll_interval,
        )
        all_pages.extend(result.pages)
        cursor = result.next_cursor
        while result.has_more and cursor:
            pages_raw = self._t.get(
                f"webgrph/crawl/{result.crawl_id}/pages",
                params={"cursor": cursor} if cursor else None,
            )
            new_pages = [
                PageNode(
                    url=p.get("url", ""),
                    depth=p.get("depth", 0),
                    title=(p.get("metadata") or {}).get("title") or p.get("title"),
                    status_code=p.get("status_code"),
                    children=p.get("children_urls", p.get("children", [])),
                )
                for p in pages_raw.get("nodes", [])
            ]
            all_pages.extend(new_pages)
            cursor = pages_raw.get("next_cursor")
            if not cursor:
                break
        return all_pages

    def get_crawl_status(self, crawl_id: str) -> Dict[str, Any]:
        """Poll crawl status and stats."""
        return self._t.get(f"webgrph/crawl/{crawl_id}")

    def get_crawl_events(self, crawl_id: str) -> Dict[str, Any]:
        """Get SSE events for a crawl."""
        return self._t.get(f"webgrph/crawl/{crawl_id}/events")

    def get_crawl_pages(self, crawl_id: str) -> Dict[str, Any]:
        """Get paginated list of discovered pages."""
        return self._t.get(f"webgrph/crawl/{crawl_id}/pages")

    def get_hierarchy(self, artifact_id: str) -> Dict[str, Any]:
        """Retrieve a stored SITE_HIERARCHY artifact by ID."""
        return self._t.get(f"webgrph/hierarchy/{artifact_id}")

    def get_job(self, job_id: str) -> Dict[str, Any]:
        """Poll a crawl job by its job ID."""
        return self._t.get(f"webgrph/jobs/{job_id}")

    # ── Analytics ─────────────────────────────────────────────────────

    def get_dashboard_summary(self) -> Dict[str, Any]:
        """Get analytics dashboard summary."""
        return self._t.get("webgrph/analytics/dashboard/summary")

    def get_error_summary(self) -> Dict[str, Any]:
        """Get error summary analytics."""
        return self._t.get("webgrph/analytics/error-summary")

    def get_job_trends(self) -> Dict[str, Any]:
        """Get job trends analytics."""
        return self._t.get("webgrph/analytics/job-trends")

    def get_discovery_patterns(self) -> Dict[str, Any]:
        """Get content discovery pattern analytics."""
        return self._t.get("webgrph/analytics/content/discovery-patterns")

    def get_efficiency_metrics(self) -> Dict[str, Any]:
        """Get scraping efficiency metrics."""
        return self._t.get("webgrph/analytics/scraping/efficiency-metrics")

    def get_site_mapping_trends(self) -> Dict[str, Any]:
        """Get site mapping trends."""
        return self._t.get("webgrph/analytics/site-maps/trends")

    def get_user_behavior_insights(self) -> Dict[str, Any]:
        """Get user behavior insights."""
        return self._t.get("webgrph/analytics/users/behavior-insights")


class AsyncWebgrphNamespace:
    """Async Webgrph operations. Access via ``async_client.webgrph``."""

    def __init__(self, transport: "_AsyncHttpTransport") -> None:
        self._t = transport

    async def crawl(
        self,
        url: str,
        max_depth: int = 3,
        max_pages: int = 100,
        include_external_links: bool = False,
        session_artifact_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        poll_timeout: float = _DEFAULT_POLL_TIMEOUT,
        poll_interval: float = _DEFAULT_POLL_INTERVAL,
    ) -> CrawlResult:
        """Async equivalent of WebgrphNamespace.crawl."""
        body: Dict[str, Any] = {
            "url": url,
            "max_depth": max_depth,
            "max_pages": max_pages,
            "include_external_links": include_external_links,
            "limit": limit,
            "offset": offset,
        }
        if session_artifact_id:
            body["session_artifact_id"] = session_artifact_id

        raw = await self._t.post("webgrph/crawl", body)
        crawl_id = raw.get("crawl_id", "")
        if not crawl_id:
            return _parse_crawl(raw, url, limit)

        final_status = await _poll_crawl_status_async(
            self._t, crawl_id, poll_timeout, poll_interval
        )
        if final_status is None:
            return CrawlResult(
                success=False,
                crawl_id=crawl_id,
                url=url,
                total_pages=0,
                max_depth_reached=0,
                error=f"Crawl timed out after {poll_timeout}s",
            )

        if final_status.get("status") == "failed":
            return CrawlResult(
                success=False,
                crawl_id=crawl_id,
                url=url,
                total_pages=0,
                max_depth_reached=0,
                error=final_status.get("error", "Crawl failed"),
            )

        pages_raw = await self._t.get(f"webgrph/crawl/{crawl_id}/pages")
        pages = [
            PageNode(
                url=p.get("url", ""),
                depth=p.get("depth", 0),
                title=(p.get("metadata") or {}).get("title") or p.get("title"),
                status_code=p.get("status_code"),
                children=p.get("children_urls", p.get("children", [])),
            )
            for p in pages_raw.get("nodes", [])
        ]
        return CrawlResult(
            success=True,
            crawl_id=crawl_id,
            url=url,
            total_pages=pages_raw.get("total", len(pages)),
            max_depth_reached=final_status.get("max_depth_reached", 0),
            pages=pages,
            artifact_id=final_status.get("artifact_id"),
            has_more=pages_raw.get("next_cursor") is not None,
            total=pages_raw.get("total", len(pages)),
            next_cursor=pages_raw.get("next_cursor"),
            error=None,
        )

    @asynccontextmanager
    async def crawl_stream(
        self,
        url: str,
        max_depth: int = 3,
        max_pages: int = 100,
        include_external_links: bool = False,
        session_artifact_id: Optional[str] = None,
    ) -> AsyncIterator[AsyncIterator[CrawlEvent]]:
        """
        Async SSE event stream for a site crawl.

        Starts the crawl via POST /webgrph/crawl, then subscribes to
        GET /webgrph/crawl/{crawl_id}/events for real-time pipeline events.

        The SSE stream uses the ``?token=`` query parameter for auth because
        ``EventSource`` cannot send custom HTTP headers.

        Usage::

            async with client.webgrph.crawl_stream("https://example.com") as events:
                async for event in events:
                    print(event.type, event.url, event.pages_found)
        """
        try:
            import httpx
        except ImportError as exc:
            raise RuntimeError("httpx is required for crawl_stream") from exc

        body: Dict[str, Any] = {
            "url": url,
            "max_depth": max_depth,
            "max_pages": max_pages,
            "include_external_links": include_external_links,
        }
        if session_artifact_id:
            body["session_artifact_id"] = session_artifact_id

        raw = await self._t.post("webgrph/crawl", body)
        crawl_id = raw.get("crawl_id", "")
        if not crawl_id:
            raise RuntimeError("Crawl start failed: no crawl_id returned")

        sse_url = self._t._url(f"webgrph/crawl/{crawl_id}/events")
        sse_url = f"{sse_url}?token={self._t._api_key}"

        async with httpx.AsyncClient(timeout=None) as http:
            async with http.stream(
                "GET",
                sse_url,
                headers={"Accept": "text/event-stream"},
            ) as response:
                from kloakd._http import _HttpTransport
                _HttpTransport._raise_for_status(response.status_code, b"")

                async def _event_iter() -> AsyncIterator[CrawlEvent]:
                    event_type = ""
                    data_lines: list[str] = []
                    async for line in response.aiter_lines():
                        line = line.rstrip("\n\r")
                        if not line:
                            if data_lines:
                                data_str = "\n".join(data_lines)
                                try:
                                    data = _json.loads(data_str)
                                    yield CrawlEvent(
                                        type=data.get("event_type", event_type or ""),
                                        url=data.get("url"),
                                        depth=data.get("depth"),
                                        pages_found=data.get("total_pages")
                                        or data.get("pages_found"),
                                        total_pages=data.get("total_pages"),
                                        artifact_id=data.get("artifact_id"),
                                        metadata=data.get("metadata", {}),
                                    )
                                except _json.JSONDecodeError:
                                    pass
                                event_type = ""
                                data_lines = []
                            continue
                        if line.startswith("event:"):
                            event_type = line[6:].strip()
                        elif line.startswith("data:"):
                            data_lines.append(line[5:].strip())
                        elif line.startswith("id:"):
                            pass

                yield _event_iter()

    async def get_crawl_status(self, crawl_id: str) -> Dict[str, Any]:
        """Async equivalent of WebgrphNamespace.get_crawl_status."""
        return await self._t.get(f"webgrph/crawl/{crawl_id}")

    async def get_crawl_events(self, crawl_id: str) -> Dict[str, Any]:
        """Async equivalent of WebgrphNamespace.get_crawl_events."""
        return await self._t.get(f"webgrph/crawl/{crawl_id}/events")

    async def get_crawl_pages(self, crawl_id: str) -> Dict[str, Any]:
        """Async equivalent of WebgrphNamespace.get_crawl_pages."""
        return await self._t.get(f"webgrph/crawl/{crawl_id}/pages")

    async def get_hierarchy(self, artifact_id: str) -> Dict[str, Any]:
        """Async equivalent of WebgrphNamespace.get_hierarchy."""
        return await self._t.get(f"webgrph/hierarchy/{artifact_id}")

    async def get_job(self, job_id: str) -> Dict[str, Any]:
        """Async equivalent of WebgrphNamespace.get_job."""
        return await self._t.get(f"webgrph/jobs/{job_id}")

    async def get_dashboard_summary(self) -> Dict[str, Any]:
        """Async equivalent of WebgrphNamespace.get_dashboard_summary."""
        return await self._t.get("webgrph/analytics/dashboard/summary")

    async def get_error_summary(self) -> Dict[str, Any]:
        """Async equivalent of WebgrphNamespace.get_error_summary."""
        return await self._t.get("webgrph/analytics/error-summary")

    async def get_job_trends(self) -> Dict[str, Any]:
        """Async equivalent of WebgrphNamespace.get_job_trends."""
        return await self._t.get("webgrph/analytics/job-trends")

    async def get_discovery_patterns(self) -> Dict[str, Any]:
        """Async equivalent of WebgrphNamespace.get_discovery_patterns."""
        return await self._t.get("webgrph/analytics/content/discovery-patterns")

    async def get_efficiency_metrics(self) -> Dict[str, Any]:
        """Async equivalent of WebgrphNamespace.get_efficiency_metrics."""
        return await self._t.get("webgrph/analytics/scraping/efficiency-metrics")

    async def get_site_mapping_trends(self) -> Dict[str, Any]:
        """Async equivalent of WebgrphNamespace.get_site_mapping_trends."""
        return await self._t.get("webgrph/analytics/site-maps/trends")

    async def get_user_behavior_insights(self) -> Dict[str, Any]:
        """Async equivalent of WebgrphNamespace.get_user_behavior_insights."""
        return await self._t.get("webgrph/analytics/users/behavior-insights")
