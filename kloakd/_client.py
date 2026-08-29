"""
KLOAKD SDK — Client classes.

Provides two client classes:

    Kloakd      — synchronous (default, uses httpx.Client internally)
    AsyncKloakd — fully async (uses httpx.AsyncClient internally)

Both expose identical namespace APIs::

    client.evadr    — EvadrNamespace
    client.webgrph  — WebgrphNamespace
    client.skanyr   — SkanyrNamespace
    client.nexus    — NexusNamespace
    client.parlyr   — ParlyrNamespace
    client.fetchyr  — FetchyrNamespace
    client.kolektr  — KolektrNamespace
"""

from __future__ import annotations

from typing import Any, Dict, Iterator, Optional

from kloakd._http import _AsyncHttpTransport, _HttpTransport
from kloakd.models import CrawlPage, CrawlProgressEvent, SiteCrawlResult
from kloakd.modules.evadr import AsyncEvadrNamespace, EvadrNamespace
from kloakd.modules.fetchyr import AsyncFetchyrNamespace, FetchyrNamespace
from kloakd.modules.kolektr import AsyncKolektrNamespace, KolektrNamespace
from kloakd.modules.nexus import AsyncNexusNamespace, NexusNamespace
from kloakd.modules.parlyr import AsyncParlyrNamespace, ParlyrNamespace
from kloakd.modules.skanyr import AsyncSkanyrNamespace, SkanyrNamespace
from kloakd.modules.webgrph import AsyncWebgrphNamespace, WebgrphNamespace

_DEFAULT_BASE_URL = "https://api.kloakd.dev"
_DEFAULT_TIMEOUT = 60.0
_DEFAULT_MAX_RETRIES = 3


class Kloakd:
    """
    KLOAKD API client — synchronous.

    The default client. All methods block until complete. For async/await
    usage, use AsyncKloakd instead.

    Args:
        api_key: Bearer API key (``sk-live-...`` or ``sk-test-...``).
            Generate at https://app.kloakd.dev/settings/api-keys.
        organization_id: Your organization UUID from the KLOAKD dashboard.
        base_url: API base URL. Defaults to ``https://api.kloakd.dev``.
        timeout: HTTP timeout in seconds. Defaults to 60.0.
        max_retries: Max retry attempts on retryable errors. Defaults to 3.
        http_client: Optional pre-built httpx.Client (useful in tests).

    Example::

        from kloakd import Kloakd

        client = Kloakd(
            api_key="sk-live-abc123",
            organization_id="your-org-uuid",
        )

        fetch = client.evadr.fetch("https://books.toscrape.com")
        data  = client.kolektr.page(
            "https://books.toscrape.com",
            schema={"title": "css:h3 a", "price": "css:p.price_color"},
            fetch_artifact_id=fetch.artifact_id,
        )
        print(data.records[:3])
    """

    def __init__(
        self,
        api_key: str,
        organization_id: str,
        base_url: str = _DEFAULT_BASE_URL,
        timeout: float = _DEFAULT_TIMEOUT,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        http_client: Optional[Any] = None,
    ) -> None:
        if not api_key or not api_key.strip():
            raise ValueError("Kloakd: api_key is required")
        if not organization_id or not organization_id.strip():
            raise ValueError("Kloakd: organization_id is required")

        self._transport = _HttpTransport(
            api_key=api_key,
            organization_id=organization_id,
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries,
            http_client=http_client,
        )

        self.evadr = EvadrNamespace(self._transport)
        self.webgrph = WebgrphNamespace(self._transport)
        self.skanyr = SkanyrNamespace(self._transport)
        self.nexus = NexusNamespace(self._transport)
        self.parlyr = ParlyrNamespace(self._transport)
        self.fetchyr = FetchyrNamespace(self._transport)
        self.kolektr = KolektrNamespace(self._transport)

    def crawl(
        self,
        url: str,
        max_depth: int = 3,
        max_pages: int = 100,
        extract_schema: Optional[Dict[str, str]] = None,
        session_artifact_id: Optional[str] = None,
        include_external_links: bool = False,
    ) -> SiteCrawlResult:
        """
        Crawl a site: discover, fetch, and optionally extract in one call.

        This is the high-level orchestrator that chains:
        1. ``webgrph.crawl()`` — BFS discovery
        2. ``evadr.fetch()`` — anti-bot fetch per page
        3. ``kolektr.page()`` — structured extraction (if ``extract_schema``)

        Per-page failures are caught and marked ``success=False`` —
        the crawl never aborts on a single page error.

        Args:
            url: Root URL to crawl.
            max_depth: Maximum BFS depth. Default 3.
            max_pages: Maximum pages to crawl. Default 100.
            extract_schema: CSS selector schema for per-page extraction.
            session_artifact_id: AUTHENTICATED_SESSION artifact from Fetchyr.
            include_external_links: Follow off-domain links.

        Returns:
            SiteCrawlResult with pages, fetch stats, and optional extracted data.

        Example::

            result = client.crawl(
                "https://example.com",
                max_depth=2,
                extract_schema={"title": "css:h1", "content": "css:article"},
            )
            print(f"Crawled {result.total_pages_discovered} pages")
            for page in result.pages:
                print(f"  {page.url} — {page.status_code}")
        """
        crawl_result = self.webgrph.crawl(
            url,
            max_depth=max_depth,
            max_pages=max_pages,
            include_external_links=include_external_links,
            session_artifact_id=session_artifact_id,
        )

        pages: list[CrawlPage] = []
        fetched = 0
        failed = 0

        for node in crawl_result.pages:
            try:
                fetch_result = self.evadr.fetch(
                    node.url,
                    session_artifact_id=session_artifact_id,
                )

                structured_data: Optional[Dict[str, Any]] = None
                if extract_schema and fetch_result.success:
                    extraction = self.kolektr.page(
                        node.url,
                        schema=extract_schema,
                        fetch_artifact_id=fetch_result.artifact_id,
                        session_artifact_id=session_artifact_id,
                    )
                    if extraction.records:
                        structured_data = extraction.records[0]

                page = CrawlPage(
                    success=fetch_result.success,
                    url=fetch_result.url,
                    status_code=fetch_result.status_code,
                    tier_used=fetch_result.tier_used,
                    html=fetch_result.html,
                    structured_data=structured_data,
                    artifact_id=fetch_result.artifact_id,
                    error=fetch_result.error,
                )
                pages.append(page)
                if page.ok:
                    fetched += 1
                else:
                    failed += 1
            except Exception as exc:
                pages.append(CrawlPage(
                    success=False,
                    url=node.url,
                    error=str(exc),
                ))
                failed += 1

        return SiteCrawlResult(
            success=True,
            url=url,
            total_pages_discovered=crawl_result.total_pages,
            pages_fetched=fetched,
            pages_failed=failed,
            pages=pages,
            crawl_artifact_id=crawl_result.artifact_id,
        )

    def crawl_stream(
        self,
        url: str,
        max_depth: int = 3,
        max_pages: int = 100,
        extract_schema: Optional[Dict[str, str]] = None,
        session_artifact_id: Optional[str] = None,
        include_external_links: bool = False,
    ) -> Iterator[CrawlProgressEvent]:
        """
        Streaming crawl: yields CrawlProgressEvent as pages are processed.

        Same as ``crawl()`` but yields events in real-time instead of
        returning a single result. Event types:
        - ``discovery_started`` — crawl discovery started
        - ``discovery_complete`` — all pages discovered
        - ``page_fetching`` — started fetching a page
        - ``page_fetched`` — page fetched successfully
        - ``page_failed`` — page fetch failed
        - ``crawl_complete`` — crawl finished, result in metadata

        Example::

            for event in client.crawl_stream("https://example.com", max_depth=2):
                if event.type == "page_fetched":
                    print(f"  [{event.page}/{event.total}] {event.url} OK")
                elif event.type == "crawl_complete":
                    print("Done!")
        """
        yield CrawlProgressEvent(type="discovery_started", url=url)

        crawl_result = self.webgrph.crawl(
            url,
            max_depth=max_depth,
            max_pages=max_pages,
            include_external_links=include_external_links,
            session_artifact_id=session_artifact_id,
        )

        total = crawl_result.total_pages
        yield CrawlProgressEvent(
            type="discovery_complete",
            url=url,
            total=total,
            metadata={"pages_found": total},
        )

        pages: list[CrawlPage] = []
        fetched = 0
        failed = 0

        for i, node in enumerate(crawl_result.pages):
            page_num = i + 1
            yield CrawlProgressEvent(
                type="page_fetching",
                url=node.url,
                page=page_num,
                total=total,
            )

            try:
                fetch_result = self.evadr.fetch(
                    node.url,
                    session_artifact_id=session_artifact_id,
                )

                structured_data: Optional[Dict[str, Any]] = None
                if extract_schema and fetch_result.success:
                    extraction = self.kolektr.page(
                        node.url,
                        schema=extract_schema,
                        fetch_artifact_id=fetch_result.artifact_id,
                        session_artifact_id=session_artifact_id,
                    )
                    if extraction.records:
                        structured_data = extraction.records[0]

                page = CrawlPage(
                    success=fetch_result.success,
                    url=fetch_result.url,
                    status_code=fetch_result.status_code,
                    tier_used=fetch_result.tier_used,
                    html=fetch_result.html,
                    structured_data=structured_data,
                    artifact_id=fetch_result.artifact_id,
                    error=fetch_result.error,
                )
                pages.append(page)

                if page.ok:
                    fetched += 1
                    yield CrawlProgressEvent(
                        type="page_fetched",
                        url=node.url,
                        page=page_num,
                        total=total,
                        success=True,
                        metadata={"tier_used": fetch_result.tier_used},
                    )
                else:
                    failed += 1
                    yield CrawlProgressEvent(
                        type="page_failed",
                        url=node.url,
                        page=page_num,
                        total=total,
                        success=False,
                        error=fetch_result.error,
                    )
            except Exception as exc:
                pages.append(CrawlPage(
                    success=False,
                    url=node.url,
                    error=str(exc),
                ))
                failed += 1
                yield CrawlProgressEvent(
                    type="page_failed",
                    url=node.url,
                    page=page_num,
                    total=total,
                    success=False,
                    error=str(exc),
                )

        result = SiteCrawlResult(
            success=True,
            url=url,
            total_pages_discovered=total,
            pages_fetched=fetched,
            pages_failed=failed,
            pages=pages,
            crawl_artifact_id=crawl_result.artifact_id,
        )
        yield CrawlProgressEvent(
            type="crawl_complete",
            url=url,
            total=total,
            success=True,
            metadata={"result": result},
        )

    def __repr__(self) -> str:
        return (
            f"Kloakd(organization_id={self._transport._organization_id!r}, "
            f"base_url={self._transport._base_url!r})"
        )


class AsyncKloakd:
    """
    KLOAKD API client — fully asynchronous.

    All namespace methods are coroutines (must be awaited). SSE stream
    methods are async context managers yielding async iterators.

    Args:
        api_key: Bearer API key.
        organization_id: Your organization UUID.
        base_url: API base URL. Defaults to ``https://api.kloakd.dev``.
        timeout: HTTP timeout in seconds. Defaults to 60.0.
        max_retries: Max retry attempts on retryable errors. Defaults to 3.
        http_client: Optional pre-built httpx.AsyncClient (useful in tests).

    Example::

        from kloakd import AsyncKloakd

        client = AsyncKloakd(
            api_key="sk-live-abc123",
            organization_id="your-org-uuid",
        )

        async def main():
            fetch = await client.evadr.fetch("https://books.toscrape.com")
            data  = await client.kolektr.page(
                "https://books.toscrape.com",
                fetch_artifact_id=fetch.artifact_id,
            )
            print(data.records[:3])

            # SSE stream
            async with client.webgrph.crawl_stream("https://books.toscrape.com") as events:
                async for event in events:
                    print(event.type, event.url)
    """

    def __init__(
        self,
        api_key: str,
        organization_id: str,
        base_url: str = _DEFAULT_BASE_URL,
        timeout: float = _DEFAULT_TIMEOUT,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        http_client: Optional[Any] = None,
    ) -> None:
        if not api_key or not api_key.strip():
            raise ValueError("AsyncKloakd: api_key is required")
        if not organization_id or not organization_id.strip():
            raise ValueError("AsyncKloakd: organization_id is required")

        self._transport = _AsyncHttpTransport(
            api_key=api_key,
            organization_id=organization_id,
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries,
            http_client=http_client,
        )

        self.evadr = AsyncEvadrNamespace(self._transport)
        self.webgrph = AsyncWebgrphNamespace(self._transport)
        self.skanyr = AsyncSkanyrNamespace(self._transport)
        self.nexus = AsyncNexusNamespace(self._transport)
        self.parlyr = AsyncParlyrNamespace(self._transport)
        self.fetchyr = AsyncFetchyrNamespace(self._transport)
        self.kolektr = AsyncKolektrNamespace(self._transport)

    async def crawl(
        self,
        url: str,
        max_depth: int = 3,
        max_pages: int = 100,
        extract_schema: Optional[Dict[str, str]] = None,
        session_artifact_id: Optional[str] = None,
        include_external_links: bool = False,
    ) -> SiteCrawlResult:
        """
        Async crawl: discover, fetch, and optionally extract in one call.

        Async equivalent of ``Kloakd.crawl()``. See that method for full docs.

        Example::

            result = await client.crawl(
                "https://example.com",
                max_depth=2,
                extract_schema={"title": "css:h1"},
            )
        """
        crawl_result = await self.webgrph.crawl(
            url,
            max_depth=max_depth,
            max_pages=max_pages,
            include_external_links=include_external_links,
            session_artifact_id=session_artifact_id,
        )

        pages: list[CrawlPage] = []
        fetched = 0
        failed = 0

        for node in crawl_result.pages:
            try:
                fetch_result = await self.evadr.fetch(
                    node.url,
                    session_artifact_id=session_artifact_id,
                )

                structured_data: Optional[Dict[str, Any]] = None
                if extract_schema and fetch_result.success:
                    extraction = await self.kolektr.page(
                        node.url,
                        schema=extract_schema,
                        fetch_artifact_id=fetch_result.artifact_id,
                        session_artifact_id=session_artifact_id,
                    )
                    if extraction.records:
                        structured_data = extraction.records[0]

                page = CrawlPage(
                    success=fetch_result.success,
                    url=fetch_result.url,
                    status_code=fetch_result.status_code,
                    tier_used=fetch_result.tier_used,
                    html=fetch_result.html,
                    structured_data=structured_data,
                    artifact_id=fetch_result.artifact_id,
                    error=fetch_result.error,
                )
                pages.append(page)
                if page.ok:
                    fetched += 1
                else:
                    failed += 1
            except Exception as exc:
                pages.append(CrawlPage(
                    success=False,
                    url=node.url,
                    error=str(exc),
                ))
                failed += 1

        return SiteCrawlResult(
            success=True,
            url=url,
            total_pages_discovered=crawl_result.total_pages,
            pages_fetched=fetched,
            pages_failed=failed,
            pages=pages,
            crawl_artifact_id=crawl_result.artifact_id,
        )

    async def crawl_stream(
        self,
        url: str,
        max_depth: int = 3,
        max_pages: int = 100,
        extract_schema: Optional[Dict[str, str]] = None,
        session_artifact_id: Optional[str] = None,
        include_external_links: bool = False,
    ) -> "AsyncIterator[CrawlProgressEvent]":
        """
        Async streaming crawl: yields CrawlProgressEvent as pages are processed.

        Async equivalent of ``Kloakd.crawl_stream()``. See that method for full docs.

        Example::

            async for event in client.crawl_stream("https://example.com", max_depth=2):
                if event.type == "page_fetched":
                    print(f"  [{event.page}/{event.total}] {event.url} OK")
        """
        yield CrawlProgressEvent(type="discovery_started", url=url)

        crawl_result = await self.webgrph.crawl(
            url,
            max_depth=max_depth,
            max_pages=max_pages,
            include_external_links=include_external_links,
            session_artifact_id=session_artifact_id,
        )

        total = crawl_result.total_pages
        yield CrawlProgressEvent(
            type="discovery_complete",
            url=url,
            total=total,
            metadata={"pages_found": total},
        )

        pages: list[CrawlPage] = []
        fetched = 0
        failed = 0

        for i, node in enumerate(crawl_result.pages):
            page_num = i + 1
            yield CrawlProgressEvent(
                type="page_fetching",
                url=node.url,
                page=page_num,
                total=total,
            )

            try:
                fetch_result = await self.evadr.fetch(
                    node.url,
                    session_artifact_id=session_artifact_id,
                )

                structured_data: Optional[Dict[str, Any]] = None
                if extract_schema and fetch_result.success:
                    extraction = await self.kolektr.page(
                        node.url,
                        schema=extract_schema,
                        fetch_artifact_id=fetch_result.artifact_id,
                        session_artifact_id=session_artifact_id,
                    )
                    if extraction.records:
                        structured_data = extraction.records[0]

                page = CrawlPage(
                    success=fetch_result.success,
                    url=fetch_result.url,
                    status_code=fetch_result.status_code,
                    tier_used=fetch_result.tier_used,
                    html=fetch_result.html,
                    structured_data=structured_data,
                    artifact_id=fetch_result.artifact_id,
                    error=fetch_result.error,
                )
                pages.append(page)

                if page.ok:
                    fetched += 1
                    yield CrawlProgressEvent(
                        type="page_fetched",
                        url=node.url,
                        page=page_num,
                        total=total,
                        success=True,
                        metadata={"tier_used": fetch_result.tier_used},
                    )
                else:
                    failed += 1
                    yield CrawlProgressEvent(
                        type="page_failed",
                        url=node.url,
                        page=page_num,
                        total=total,
                        success=False,
                        error=fetch_result.error,
                    )
            except Exception as exc:
                pages.append(CrawlPage(
                    success=False,
                    url=node.url,
                    error=str(exc),
                ))
                failed += 1
                yield CrawlProgressEvent(
                    type="page_failed",
                    url=node.url,
                    page=page_num,
                    total=total,
                    success=False,
                    error=str(exc),
                )

        result = SiteCrawlResult(
            success=True,
            url=url,
            total_pages_discovered=total,
            pages_fetched=fetched,
            pages_failed=failed,
            pages=pages,
            crawl_artifact_id=crawl_result.artifact_id,
        )
        yield CrawlProgressEvent(
            type="crawl_complete",
            url=url,
            total=total,
            success=True,
            metadata={"result": result},
        )

    def __repr__(self) -> str:
        return (
            f"AsyncKloakd(organization_id={self._transport._organization_id!r}, "
            f"base_url={self._transport._base_url!r})"
        )
