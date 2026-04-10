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
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, AsyncIterator, Dict, List, Optional

from kloakd.models import CrawlEvent, CrawlResult, PageNode

if TYPE_CHECKING:
    from kloakd._http import _AsyncHttpTransport, _HttpTransport


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
    return CrawlResult(
        success=raw.get("success", False),
        crawl_id=raw.get("crawl_id", ""),
        url=raw.get("url", url),
        total_pages=raw.get("total_pages", len(pages)),
        max_depth_reached=raw.get("max_depth_reached", 0),
        pages=pages,
        artifact_id=raw.get("artifact_id"),
        has_more=raw.get("has_more", False),
        total=total,
        error=raw.get("error"),
    )


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
    ) -> CrawlResult:
        """
        Crawl a site and produce a SITE_HIERARCHY artifact.

        Args:
            url: Seed URL.
            max_depth: Maximum BFS depth. Default 3.
            max_pages: Maximum pages to crawl. Default 100.
            include_external_links: Follow off-domain links.
            session_artifact_id: AUTHENTICATED_SESSION artifact from Fetchyr.
            limit: Max pages in this response (pagination). Default 100.
            offset: Pagination offset. Default 0.

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
        return _parse_crawl(raw, url, limit)

    def crawl_all(
        self,
        url: str,
        max_depth: int = 3,
        max_pages: int = 1000,
        include_external_links: bool = False,
        session_artifact_id: Optional[str] = None,
    ) -> List[PageNode]:
        """
        Auto-paginate crawl results, returning all discovered pages.

        Returns:
            Complete list of PageNode objects.
        """
        all_pages: List[PageNode] = []
        offset = 0
        while True:
            result = self.crawl(
                url,
                max_depth=max_depth,
                max_pages=max_pages,
                include_external_links=include_external_links,
                session_artifact_id=session_artifact_id,
                limit=100,
                offset=offset,
            )
            all_pages.extend(result.pages)
            if not result.has_more:
                break
            offset += len(result.pages)
        return all_pages

    def get_hierarchy(self, artifact_id: str) -> Dict[str, Any]:
        """Retrieve a stored SITE_HIERARCHY artifact by ID."""
        return self._t.get(f"webgrph/hierarchy/{artifact_id}")

    def get_job(self, job_id: str) -> Dict[str, Any]:
        """Poll a crawl job by its job ID."""
        return self._t.get(f"webgrph/jobs/{job_id}")


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
        return _parse_crawl(raw, url, limit)

    @asynccontextmanager
    async def crawl_stream(
        self,
        url: str,
        max_depth: int = 3,
        max_pages: int = 100,
    ) -> AsyncIterator[AsyncIterator[CrawlEvent]]:
        """
        Async SSE event stream for a site crawl.

        Usage::

            async with client.webgrph.crawl_stream("https://example.com") as events:
                async for event in events:
                    print(event.type, event.url, event.pages_found)
        """
        try:
            import httpx
        except ImportError as exc:
            raise RuntimeError("httpx is required for crawl_stream") from exc

        url_path = self._t._url("webgrph/crawl/stream")
        headers = self._t._auth_headers()
        headers["Accept"] = "text/event-stream"

        async with httpx.AsyncClient(timeout=None) as http:
            async with http.stream(
                "POST",
                url_path,
                json={"url": url, "max_depth": max_depth, "max_pages": max_pages},
                headers=headers,
            ) as response:
                from kloakd._http import _HttpTransport
                _HttpTransport._raise_for_status(response.status_code, b"")

                async def _event_iter() -> AsyncIterator[CrawlEvent]:
                    async for line in response.aiter_lines():
                        line = line.strip()
                        if not line.startswith("data:"):
                            continue
                        data_str = line[5:].strip()
                        if not data_str:
                            continue
                        try:
                            data = _json.loads(data_str)
                            yield CrawlEvent(
                                type=data.get("type", ""),
                                url=data.get("url"),
                                depth=data.get("depth"),
                                pages_found=data.get("pages_found"),
                                metadata=data.get("metadata", {}),
                            )
                        except _json.JSONDecodeError:
                            continue

                yield _event_iter()

    async def get_hierarchy(self, artifact_id: str) -> Dict[str, Any]:
        """Async equivalent of WebgrphNamespace.get_hierarchy."""
        return await self._t.get(f"webgrph/hierarchy/{artifact_id}")

    async def get_job(self, job_id: str) -> Dict[str, Any]:
        """Async equivalent of WebgrphNamespace.get_job."""
        return await self._t.get(f"webgrph/jobs/{job_id}")
