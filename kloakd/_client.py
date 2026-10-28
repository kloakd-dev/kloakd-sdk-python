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

from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Union

from kloakd._handoff import DEFAULT_POLL_INTERVAL, DEFAULT_POLL_TIMEOUT, PollOptions
from kloakd._http import _AsyncHttpTransport, _HttpTransport
from kloakd.errors import (
    AuthenticationError,
    BillingUnavailableError,
    NotEntitledError,
    PaymentRequiredError,
    QuotaExceededError,
    RateLimitError,
)
from kloakd.models import (
    CrawlPage,
    CrawlProgressEvent,
    CrawlResult,
    FetchResult,
    SiteCrawlResult,
)
from kloakd.modules._ops import as_dict
from kloakd.modules.evadr import AsyncEvadrNamespace, EvadrNamespace
from kloakd.modules.fetchyr import AsyncFetchyrNamespace, FetchyrNamespace
from kloakd.modules.kolektr import AsyncKolektrNamespace, KolektrNamespace
from kloakd.modules.nexus import AsyncNexusNamespace, NexusNamespace
from kloakd.modules.parlyr import AsyncParlyrNamespace, ParlyrNamespace
from kloakd.modules.skanyr import AsyncSkanyrNamespace, SkanyrNamespace
from kloakd.modules.webgrph import AsyncWebgrphNamespace, WebgrphNamespace

_DEFAULT_BASE_URL = "https://api.kloakd.dev"
# Above the API's 85 s synchronous wait, so a long request receives its 202
# hand-off instead of timing out (kobe-scraper kernel/sync_handoff.py).
_DEFAULT_TIMEOUT = 100.0
_DEFAULT_MAX_RETRIES = 3

#: Errors that end a crawl() instead of failing one page: the next page
#: would fail the same way (billing, plan, key or rate limit).
_FATAL_ERRORS = (
    PaymentRequiredError,
    QuotaExceededError,
    BillingUnavailableError,
    NotEntitledError,
    AuthenticationError,
    RateLimitError,
)

ExtractSchema = Union[Dict[str, Any], List[Dict[str, Any]]]


def _page(fetch: FetchResult, structured_data: Optional[Dict[str, Any]]) -> CrawlPage:
    return CrawlPage(
        success=fetch.success,
        url=fetch.url,
        status_code=fetch.status_code,
        tier_used=fetch.tier_used,
        html=fetch.html,
        structured_data=structured_data,
        artifact_id=fetch.artifact_id,
        error=fetch.error,
    )


def _site_result(
    url: str, crawl: CrawlResult, pages: List[CrawlPage]
) -> SiteCrawlResult:
    """The crawl's own success and error, with the per-page counts."""
    fetched = sum(1 for p in pages if p.ok)
    return SiteCrawlResult(
        success=crawl.success,
        url=url,
        total_pages_discovered=crawl.total_pages,
        pages_fetched=fetched,
        pages_failed=len(pages) - fetched,
        pages=pages,
        crawl_artifact_id=crawl.artifact_id,
        error=crawl.error,
    )


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
        timeout: HTTP timeout in seconds. Defaults to 100.0, above the
            API's 85 s synchronous wait, so a long request gets its 202
            hand-off rather than a client timeout.
        max_retries: Max retry attempts on retryable errors. Defaults to 3.
        http_client: Optional pre-built httpx.Client (useful in tests).
        poll_interval: Seconds before the first poll of a request the API
            hands off as a job (HTTP 202); each later wait is half as long
            again, up to 15 s. Defaults to 3.0.
        poll_timeout: Seconds to follow a handed-off request before
            JobTimeoutError. Defaults to 900 (15 minutes).

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
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        poll_timeout: float = DEFAULT_POLL_TIMEOUT,
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
            poll=PollOptions(poll_interval, poll_timeout),
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
        extract_schema: Optional[ExtractSchema] = None,
        session_artifact_id: Optional[str] = None,
        include_external_links: bool = False,
        poll_timeout: float = 300.0,
        poll_interval: float = 2.0,
    ) -> SiteCrawlResult:
        """
        Crawl a site: discover, fetch, and optionally extract in one call.

        This is the high-level orchestrator that chains:
        1. ``webgrph.crawl()`` — BFS discovery (polls until crawl completes)
        2. ``evadr.fetch()`` — anti-bot fetch per page
        3. ``kolektr.page()`` — structured extraction (if ``extract_schema``)

        A page that fails is marked ``success=False`` and the crawl goes on;
        billing, plan, API-key and rate-limit errors (PaymentRequiredError,
        QuotaExceededError, BillingUnavailableError, NotEntitledError,
        AuthenticationError, RateLimitError) are raised, since every later
        page would fail the same way. The result's ``success`` and ``error``
        are the crawl's own (False, with the reason, when the crawl failed
        or was still running after ``poll_timeout``).

        Args:
            url: Root URL to crawl.
            max_depth: Maximum BFS depth. Default 3.
            max_pages: Maximum pages to crawl. Default 100.
            extract_schema: Per-page extraction schema, as for
                ``kolektr.page``: the ``{field: "css:selector"}`` shorthand,
                a list of fields, or a full schema_spec.
            session_artifact_id: AUTHENTICATED_SESSION artifact from Fetchyr.
            include_external_links: Follow off-domain links.
            poll_timeout: Max seconds to wait for crawl discovery. Default 300.
            poll_interval: Seconds between status polls. Default 2.

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
            poll_timeout=poll_timeout,
            poll_interval=poll_interval,
        )

        pages: List[CrawlPage] = []
        for node in crawl_result.pages:
            pages.append(self._crawl_page(node.url, extract_schema, session_artifact_id))
        return _site_result(url, crawl_result, pages)

    def crawl_stream(
        self,
        url: str,
        max_depth: int = 3,
        max_pages: int = 100,
        extract_schema: Optional[ExtractSchema] = None,
        session_artifact_id: Optional[str] = None,
        include_external_links: bool = False,
        poll_timeout: float = 300.0,
        poll_interval: float = 2.0,
    ) -> Iterator[CrawlProgressEvent]:
        """
        Streaming crawl: yields CrawlProgressEvent as pages are processed.

        Same as ``crawl()`` but yields events in real-time instead of
        returning a single result. Event types:
        - ``discovery_started`` — crawl discovery started (emitted by the SDK)
        - ``discovery_complete`` — the crawl finished (``success``/``error``
          are the crawl's own)
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
            poll_timeout=poll_timeout,
            poll_interval=poll_interval,
        )

        total = crawl_result.total_pages
        yield CrawlProgressEvent(
            type="discovery_complete",
            url=url,
            total=total,
            success=crawl_result.success,
            error=crawl_result.error,
            metadata={"pages_found": total},
        )

        pages: List[CrawlPage] = []
        for i, node in enumerate(crawl_result.pages):
            page_num = i + 1
            yield CrawlProgressEvent(
                type="page_fetching", url=node.url, page=page_num, total=total
            )
            page = self._crawl_page(node.url, extract_schema, session_artifact_id)
            pages.append(page)
            if page.ok:
                yield CrawlProgressEvent(
                    type="page_fetched",
                    url=node.url,
                    page=page_num,
                    total=total,
                    success=True,
                    metadata={"tier_used": page.tier_used},
                )
            else:
                yield CrawlProgressEvent(
                    type="page_failed",
                    url=node.url,
                    page=page_num,
                    total=total,
                    success=False,
                    error=page.error,
                )

        result = _site_result(url, crawl_result, pages)
        yield CrawlProgressEvent(
            type="crawl_complete",
            url=url,
            total=total,
            success=result.success,
            error=result.error,
            metadata={"result": result},
        )

    def get_handoff(self, job_id: str) -> Dict[str, Any]:
        """The state of a request the API handed off as a job (HTTP 202):
        ``{"job_id", "status": "running" | "completed" | "failed",
        "result"?, "error"?}`` (``GET /api/v1/organizations/{org}/handoff/{job_id}``,
        kobe-scraper kernel/sync_handoff.py). A job unknown or expired (an
        hour after it ends) raises ApiError 404."""
        url = self._transport._handoff_url(job_id)
        return as_dict(self._transport._send("GET", url)[1])

    def wait_for_handoff(
        self,
        job_id: str,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        timeout: float = DEFAULT_POLL_TIMEOUT,
    ) -> Dict[str, Any]:
        """Poll a handed-off request until it completes; returns the route's
        own response body. Use it to resume after JobTimeoutError
        (``e.job_id``). A failed or expired job raises JobFailedError."""
        return self._transport.follow(
            job_id,
            self._transport._handoff_url(job_id),
            PollOptions(poll_interval, timeout),
        )

    def _crawl_page(
        self,
        url: str,
        extract_schema: Optional[ExtractSchema],
        session_artifact_id: Optional[str],
    ) -> CrawlPage:
        """Fetch (and extract) one crawled page. A page error marks only that
        page failed; billing, plan, key and rate-limit errors are raised."""
        try:
            fetch = self.evadr.fetch(url, session_artifact_id=session_artifact_id)
            structured_data: Optional[Dict[str, Any]] = None
            if extract_schema and fetch.success:
                extraction = self.kolektr.page(
                    url,
                    schema=extract_schema,
                    fetch_artifact_id=fetch.artifact_id,
                    session_artifact_id=session_artifact_id,
                )
                if extraction.records:
                    structured_data = extraction.records[0]
            return _page(fetch, structured_data)
        except _FATAL_ERRORS:
            raise
        except Exception as exc:
            return CrawlPage(success=False, url=url, error=str(exc))

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
        timeout: HTTP timeout in seconds. Defaults to 100.0, above the
            API's 85 s synchronous wait, so a long request gets its 202
            hand-off rather than a client timeout.
        max_retries: Max retry attempts on retryable errors. Defaults to 3.
        http_client: Optional pre-built httpx.AsyncClient (useful in tests).
        poll_interval, poll_timeout: As for Kloakd.

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
            async for event in client.webgrph.crawl_stream("https://books.toscrape.com"):
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
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        poll_timeout: float = DEFAULT_POLL_TIMEOUT,
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
            poll=PollOptions(poll_interval, poll_timeout),
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
        extract_schema: Optional[ExtractSchema] = None,
        session_artifact_id: Optional[str] = None,
        include_external_links: bool = False,
        poll_timeout: float = 300.0,
        poll_interval: float = 2.0,
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
            poll_timeout=poll_timeout,
            poll_interval=poll_interval,
        )

        pages: List[CrawlPage] = []
        for node in crawl_result.pages:
            pages.append(await self._crawl_page(node.url, extract_schema, session_artifact_id))
        return _site_result(url, crawl_result, pages)

    async def crawl_stream(
        self,
        url: str,
        max_depth: int = 3,
        max_pages: int = 100,
        extract_schema: Optional[ExtractSchema] = None,
        session_artifact_id: Optional[str] = None,
        include_external_links: bool = False,
        poll_timeout: float = 300.0,
        poll_interval: float = 2.0,
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
            poll_timeout=poll_timeout,
            poll_interval=poll_interval,
        )

        total = crawl_result.total_pages
        yield CrawlProgressEvent(
            type="discovery_complete",
            url=url,
            total=total,
            success=crawl_result.success,
            error=crawl_result.error,
            metadata={"pages_found": total},
        )

        pages: List[CrawlPage] = []
        for i, node in enumerate(crawl_result.pages):
            page_num = i + 1
            yield CrawlProgressEvent(
                type="page_fetching", url=node.url, page=page_num, total=total
            )
            page = await self._crawl_page(node.url, extract_schema, session_artifact_id)
            pages.append(page)
            if page.ok:
                yield CrawlProgressEvent(
                    type="page_fetched",
                    url=node.url,
                    page=page_num,
                    total=total,
                    success=True,
                    metadata={"tier_used": page.tier_used},
                )
            else:
                yield CrawlProgressEvent(
                    type="page_failed",
                    url=node.url,
                    page=page_num,
                    total=total,
                    success=False,
                    error=page.error,
                )

        result = _site_result(url, crawl_result, pages)
        yield CrawlProgressEvent(
            type="crawl_complete",
            url=url,
            total=total,
            success=result.success,
            error=result.error,
            metadata={"result": result},
        )

    async def get_handoff(self, job_id: str) -> Dict[str, Any]:
        """Async equivalent of Kloakd.get_handoff: the state of a request the API handed off as a job (HTTP 202):
        ``{"job_id", "status": "running" | "completed" | "failed",
        "result"?, "error"?}`` (``GET /api/v1/organizations/{org}/handoff/{job_id}``,
        kobe-scraper kernel/sync_handoff.py). A job unknown or expired (an
        hour after it ends) raises ApiError 404."""
        url = self._transport._handoff_url(job_id)
        return as_dict((await self._transport._send("GET", url))[1])

    async def wait_for_handoff(
        self,
        job_id: str,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        timeout: float = DEFAULT_POLL_TIMEOUT,
    ) -> Dict[str, Any]:
        """Async equivalent of Kloakd.wait_for_handoff: poll a handed-off request until it completes; returns the route's
        own response body. Use it to resume after JobTimeoutError
        (``e.job_id``). A failed or expired job raises JobFailedError."""
        return await self._transport.follow(
            job_id,
            self._transport._handoff_url(job_id),
            PollOptions(poll_interval, timeout),
        )

    async def _crawl_page(
        self,
        url: str,
        extract_schema: Optional[ExtractSchema],
        session_artifact_id: Optional[str],
    ) -> CrawlPage:
        """Fetch (and extract) one crawled page. A page error marks only that
        page failed; billing, plan, key and rate-limit errors are raised."""
        try:
            fetch = await self.evadr.fetch(url, session_artifact_id=session_artifact_id)
            structured_data: Optional[Dict[str, Any]] = None
            if extract_schema and fetch.success:
                extraction = await self.kolektr.page(
                    url,
                    schema=extract_schema,
                    fetch_artifact_id=fetch.artifact_id,
                    session_artifact_id=session_artifact_id,
                )
                if extraction.records:
                    structured_data = extraction.records[0]
            return _page(fetch, structured_data)
        except _FATAL_ERRORS:
            raise
        except Exception as exc:
            return CrawlPage(success=False, url=url, error=str(exc))

    def __repr__(self) -> str:
        return (
            f"AsyncKloakd(organization_id={self._transport._organization_id!r}, "
            f"base_url={self._transport._base_url!r})"
        )
