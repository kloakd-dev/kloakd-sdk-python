"""
KLOAKD SDK — Webgrph module namespace.

Webgrph maps a site: a breadth-first crawl that builds its page hierarchy.
The API answers a crawl request with 202 and crawls in the background;
``crawl`` waits for it and loads every page node.

Usage::

    crawl = client.webgrph.crawl("https://example.com", max_depth=3)
    print(crawl.status, crawl.total_pages)
    site = client.skanyr.site_from_crawl(crawl.crawl_id)
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any, AsyncIterator, Dict, Iterator, List, Optional

from kloakd.models import CrawlEvent, CrawlResult, PageNode
from kloakd.modules._ops import Op, _Op, arun, as_list, compact, run

if TYPE_CHECKING:
    from kloakd._http import _AsyncHttpTransport, _HttpTransport

_DEFAULT_POLL_TIMEOUT = 30 * 60.0
_DEFAULT_POLL_INTERVAL = 3.0
_FINISHED = ("completed", "failed", "cancelled")


def _node(p: Dict[str, Any]) -> PageNode:
    return PageNode(
        url=p.get("url", ""),
        depth=int(p.get("depth") or 0),
        title=(p.get("metadata") or {}).get("title") or p.get("title"),
        status_code=p.get("status_code"),
        children=p.get("children_urls", p.get("children", [])) or [],
    )


def _crawl_body(
    url: str,
    max_depth: int,
    max_pages: int,
    include_external_links: bool,
    session_artifact_id: Optional[str],
    fast_mode: Optional[bool],
    capture_mode: Optional[str],
    scope: Optional[Dict[str, Any]],
    budget: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    return compact(
        {
            "url": url,
            "max_depth": max_depth,
            "max_pages": max_pages,
            "include_external_links": include_external_links,
            "session_artifact_id": session_artifact_id,
            "fast_mode": fast_mode,
            "capture_mode": capture_mode,
            "scope": scope,
            "budget": budget,
        }
    )


def _pages_params(cursor: Optional[str], limit: int) -> Dict[str, Any]:
    return compact({"cursor": cursor, "limit": limit})


def _result(
    status: Dict[str, Any], url: str, pages: List[PageNode], error: Optional[str] = None
) -> CrawlResult:
    state = str(status.get("status") or "")
    return CrawlResult(
        success=state == "completed" and error is None,
        crawl_id=str(status.get("crawl_id") or ""),
        url=url,
        total_pages=int(status.get("total_pages") or len(pages)),
        max_depth_reached=int(status.get("max_depth_reached") or 0),
        pages=pages,
        artifact_id=status.get("artifact_id"),
        has_more=False,
        total=len(pages),
        next_cursor=None,
        error=error or status.get("error"),
        status=state,
    )


def _event(data: Dict[str, Any], crawl_id: str) -> CrawlEvent:
    meta = data.get("metadata") or {}
    return CrawlEvent(
        type=str(data.get("event_type") or data.get("type") or ""),
        url=data.get("url") or meta.get("url"),
        depth=data.get("depth"),
        pages_found=data.get("pages_found") or meta.get("pages_found"),
        total_pages=data.get("total_pages") or meta.get("total_pages"),
        artifact_id=data.get("artifact_id") or meta.get("artifact_id"),
        stage_id=data.get("stage_id"),
        sub_status=data.get("sub_status"),
        progress_pct=data.get("progress_pct"),
        metadata={"crawl_id": crawl_id, **(meta or data)},
    )


def _ops_session(
    url: str,
    selected_nodes: Optional[List[Any]],
    hierarchy_data: Optional[Dict[str, Any]],
    session_id: Optional[str],
    last_crawl_id: Optional[str],
) -> "Op[Dict[str, Any]]":
    return _Op(
        "POST",
        "webgrph/sessions",
        compact(
            {
                "url": url,
                "selected_nodes": selected_nodes or [],
                "hierarchy_data": hierarchy_data,
                "session_id": session_id,
                "last_crawl_id": last_crawl_id,
            }
        ),
    )


class WebgrphNamespace:
    """Synchronous Webgrph operations. Access via ``client.webgrph``."""

    def __init__(self, transport: "_HttpTransport") -> None:
        self._t = transport

    def start_crawl(
        self,
        url: str,
        max_depth: int = 3,
        max_pages: int = 100,
        include_external_links: bool = False,
        session_artifact_id: Optional[str] = None,
        fast_mode: Optional[bool] = None,
        capture_mode: Optional[str] = None,
        scope: Optional[Dict[str, Any]] = None,
        budget: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Start a crawl (the API answers 202); returns its crawl id."""
        raw = self._t.post(
            "webgrph/crawl",
            _crawl_body(
                url,
                max_depth,
                max_pages,
                include_external_links,
                session_artifact_id,
                fast_mode,
                capture_mode,
                scope,
                budget,
            ),
        )
        return str(raw.get("crawl_id") or "")

    def crawl(
        self,
        url: str,
        max_depth: int = 3,
        max_pages: int = 100,
        include_external_links: bool = False,
        session_artifact_id: Optional[str] = None,
        fast_mode: Optional[bool] = None,
        capture_mode: Optional[str] = None,
        scope: Optional[Dict[str, Any]] = None,
        budget: Optional[Dict[str, Any]] = None,
        wait: bool = True,
        poll_timeout: float = _DEFAULT_POLL_TIMEOUT,
        poll_interval: float = _DEFAULT_POLL_INTERVAL,
    ) -> CrawlResult:
        """
        Crawl a site: start it, wait until it finishes, and load every page
        node. A failed crawl, or one still running after ``poll_timeout``,
        comes back with ``success=False`` and ``error`` set. With
        ``wait=False`` only the crawl id is returned (status "queued").
        """
        crawl_id = self.start_crawl(
            url,
            max_depth,
            max_pages,
            include_external_links,
            session_artifact_id,
            fast_mode,
            capture_mode,
            scope,
            budget,
        )
        if not wait:
            return _result({"crawl_id": crawl_id, "status": "queued"}, url, [])
        deadline = time.monotonic() + poll_timeout
        status = self.get_crawl_status(crawl_id)
        while status.get("status") not in _FINISHED:
            if time.monotonic() + poll_interval > deadline:
                return _result(
                    status,
                    url,
                    [],
                    error=f"Crawl {crawl_id} still running after {poll_timeout}s",
                )
            time.sleep(poll_interval)
            status = self.get_crawl_status(crawl_id)
        if status.get("status") != "completed":
            return _result(
                status,
                url,
                [],
                error=status.get("error") or f"Crawl {status.get('status')}",
            )
        return _result(status, url, self.crawl_all_pages(crawl_id))

    def crawl_all(self, url: str, **kwargs: Any) -> List[PageNode]:
        """Every page node of a finished crawl (same options as ``crawl``)."""
        return self.crawl(url, **kwargs).pages

    def crawl_stream(
        self,
        url: str,
        max_depth: int = 3,
        max_pages: int = 100,
        include_external_links: bool = False,
        session_artifact_id: Optional[str] = None,
    ) -> Iterator[CrawlEvent]:
        """Start a crawl and yield its progress events (Server-Sent Events)."""
        crawl_id = self.start_crawl(
            url, max_depth, max_pages, include_external_links, session_artifact_id
        )
        for data in self.crawl_events(crawl_id):
            yield _event(data, crawl_id)

    def get_crawl_status(self, crawl_id: str) -> Dict[str, Any]:
        return run(self._t, _Op("GET", f"webgrph/crawl/{crawl_id}"))

    def cancel_crawl(self, crawl_id: str) -> Dict[str, Any]:
        return run(self._t, _Op("POST", f"webgrph/crawl/{crawl_id}/cancel", {}))

    def crawl_events(
        self, crawl_id: str, last_sequence: Optional[int] = None
    ) -> Iterator[Dict[str, Any]]:
        """A crawl's progress events; ``last_sequence`` resumes after an event already seen."""
        params = {"last_sequence": last_sequence} if last_sequence is not None else None
        for _name, data in self._t.iter_sse(
            "GET", f"webgrph/crawl/{crawl_id}/events", params=params
        ):
            yield data

    def get_crawl_pages(
        self, crawl_id: str, cursor: Optional[str] = None, limit: int = 500
    ) -> Dict[str, Any]:
        """One page of a crawl's hierarchy: ``nodes``, ``next_cursor``, ``total``."""
        return run(
            self._t,
            _Op(
                "GET",
                f"webgrph/crawl/{crawl_id}/pages",
                params=_pages_params(cursor, limit),
            ),
        )

    def crawl_all_pages(self, crawl_id: str) -> List[PageNode]:
        """Every page node of a crawl, following the cursor."""
        nodes: List[PageNode] = []
        cursor: Optional[str] = None
        while True:
            page = self.get_crawl_pages(crawl_id, cursor=cursor)
            nodes.extend(_node(n) for n in page.get("nodes") or [])
            cursor = page.get("next_cursor")
            if not cursor:
                return nodes

    # ── Reader view, detected APIs, sessions (moved from skanyr in 0.3) ──

    def reader_view(
        self,
        url: str,
        crawl_id: Optional[str] = None,
        session_artifact_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        return run(
            self._t,
            _Op(
                "POST",
                "webgrph/reader-view",
                compact(
                    {
                        "url": url,
                        "crawl_id": crawl_id,
                        "session_artifact_id": session_artifact_id,
                    }
                ),
            ),
        )

    def detected_apis(self, page_url: str) -> Dict[str, Any]:
        return run(
            self._t, _Op("GET", "webgrph/detected-apis", params={"page_url": page_url})
        )

    def list_sessions(self, active_only: Optional[bool] = None) -> List[Dict[str, Any]]:
        return run(
            self._t,
            _Op(
                "GET",
                "webgrph/sessions",
                params=compact({"active_only": active_only}),
                parse=as_list,
            ),
        )

    def save_session(
        self,
        url: str,
        selected_nodes: Optional[List[Any]] = None,
        hierarchy_data: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
        last_crawl_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        return run(
            self._t,
            _ops_session(
                url, selected_nodes, hierarchy_data, session_id, last_crawl_id
            ),
        )

    def get_session(self, session_id: str) -> Dict[str, Any]:
        return run(self._t, _Op("GET", f"webgrph/sessions/{session_id}"))

    def delete_session(self, session_id: str) -> None:
        run(self._t, _Op("DELETE", f"webgrph/sessions/{session_id}"))

    def end_session(self, session_id: str) -> Dict[str, Any]:
        return run(self._t, _Op("POST", f"webgrph/sessions/{session_id}/end", {}))

    def update_session_job(self, session_id: str, job_id: str) -> Dict[str, Any]:
        return run(
            self._t,
            _Op(
                "PATCH", f"webgrph/sessions/{session_id}/job", params={"job_id": job_id}
            ),
        )

    # ── Analytics ─────────────────────────────────────────────────────────

    def get_dashboard_summary(self) -> Dict[str, Any]:
        return run(self._t, _Op("GET", "webgrph/analytics/dashboard/summary"))

    def get_error_summary(self) -> Dict[str, Any]:
        return run(self._t, _Op("GET", "webgrph/analytics/error-summary"))

    def get_job_trends(self) -> Dict[str, Any]:
        return run(self._t, _Op("GET", "webgrph/analytics/job-trends"))

    def get_discovery_patterns(self) -> Dict[str, Any]:
        return run(self._t, _Op("GET", "webgrph/analytics/content/discovery-patterns"))

    def get_efficiency_metrics(self) -> Dict[str, Any]:
        return run(self._t, _Op("GET", "webgrph/analytics/scraping/efficiency-metrics"))

    def get_site_mapping_trends(self) -> Dict[str, Any]:
        return run(self._t, _Op("GET", "webgrph/analytics/site-maps/trends"))

    def get_user_behavior_insights(self) -> Dict[str, Any]:
        return run(self._t, _Op("GET", "webgrph/analytics/users/behavior-insights"))


class AsyncWebgrphNamespace:
    """Async Webgrph operations. Access via ``async_client.webgrph``."""

    def __init__(self, transport: "_AsyncHttpTransport") -> None:
        self._t = transport

    async def start_crawl(
        self,
        url: str,
        max_depth: int = 3,
        max_pages: int = 100,
        include_external_links: bool = False,
        session_artifact_id: Optional[str] = None,
        fast_mode: Optional[bool] = None,
        capture_mode: Optional[str] = None,
        scope: Optional[Dict[str, Any]] = None,
        budget: Optional[Dict[str, Any]] = None,
    ) -> str:
        raw = await self._t.post(
            "webgrph/crawl",
            _crawl_body(
                url,
                max_depth,
                max_pages,
                include_external_links,
                session_artifact_id,
                fast_mode,
                capture_mode,
                scope,
                budget,
            ),
        )
        return str(raw.get("crawl_id") or "")

    async def crawl(
        self,
        url: str,
        max_depth: int = 3,
        max_pages: int = 100,
        include_external_links: bool = False,
        session_artifact_id: Optional[str] = None,
        fast_mode: Optional[bool] = None,
        capture_mode: Optional[str] = None,
        scope: Optional[Dict[str, Any]] = None,
        budget: Optional[Dict[str, Any]] = None,
        wait: bool = True,
        poll_timeout: float = _DEFAULT_POLL_TIMEOUT,
        poll_interval: float = _DEFAULT_POLL_INTERVAL,
    ) -> CrawlResult:
        """Async equivalent of WebgrphNamespace.crawl."""
        crawl_id = await self.start_crawl(
            url,
            max_depth,
            max_pages,
            include_external_links,
            session_artifact_id,
            fast_mode,
            capture_mode,
            scope,
            budget,
        )
        if not wait:
            return _result({"crawl_id": crawl_id, "status": "queued"}, url, [])
        deadline = time.monotonic() + poll_timeout
        status = await self.get_crawl_status(crawl_id)
        while status.get("status") not in _FINISHED:
            if time.monotonic() + poll_interval > deadline:
                return _result(
                    status,
                    url,
                    [],
                    error=f"Crawl {crawl_id} still running after {poll_timeout}s",
                )
            await asyncio.sleep(poll_interval)
            status = await self.get_crawl_status(crawl_id)
        if status.get("status") != "completed":
            return _result(
                status,
                url,
                [],
                error=status.get("error") or f"Crawl {status.get('status')}",
            )
        return _result(status, url, await self.crawl_all_pages(crawl_id))

    async def crawl_all(self, url: str, **kwargs: Any) -> List[PageNode]:
        return (await self.crawl(url, **kwargs)).pages

    async def crawl_stream(
        self,
        url: str,
        max_depth: int = 3,
        max_pages: int = 100,
        include_external_links: bool = False,
        session_artifact_id: Optional[str] = None,
    ) -> AsyncIterator[CrawlEvent]:
        """Start a crawl and yield its progress events (Server-Sent Events)."""
        crawl_id = await self.start_crawl(
            url, max_depth, max_pages, include_external_links, session_artifact_id
        )
        async for data in self.crawl_events(crawl_id):
            yield _event(data, crawl_id)

    async def get_crawl_status(self, crawl_id: str) -> Dict[str, Any]:
        return await arun(self._t, _Op("GET", f"webgrph/crawl/{crawl_id}"))

    async def cancel_crawl(self, crawl_id: str) -> Dict[str, Any]:
        return await arun(self._t, _Op("POST", f"webgrph/crawl/{crawl_id}/cancel", {}))

    async def crawl_events(
        self, crawl_id: str, last_sequence: Optional[int] = None
    ) -> AsyncIterator[Dict[str, Any]]:
        params = {"last_sequence": last_sequence} if last_sequence is not None else None
        async for _name, data in self._t.aiter_sse(
            "GET", f"webgrph/crawl/{crawl_id}/events", params=params
        ):
            yield data

    async def get_crawl_pages(
        self, crawl_id: str, cursor: Optional[str] = None, limit: int = 500
    ) -> Dict[str, Any]:
        return await arun(
            self._t,
            _Op(
                "GET",
                f"webgrph/crawl/{crawl_id}/pages",
                params=_pages_params(cursor, limit),
            ),
        )

    async def crawl_all_pages(self, crawl_id: str) -> List[PageNode]:
        nodes: List[PageNode] = []
        cursor: Optional[str] = None
        while True:
            page = await self.get_crawl_pages(crawl_id, cursor=cursor)
            nodes.extend(_node(n) for n in page.get("nodes") or [])
            cursor = page.get("next_cursor")
            if not cursor:
                return nodes

    async def reader_view(
        self,
        url: str,
        crawl_id: Optional[str] = None,
        session_artifact_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        return await arun(
            self._t,
            _Op(
                "POST",
                "webgrph/reader-view",
                compact(
                    {
                        "url": url,
                        "crawl_id": crawl_id,
                        "session_artifact_id": session_artifact_id,
                    }
                ),
            ),
        )

    async def detected_apis(self, page_url: str) -> Dict[str, Any]:
        return await arun(
            self._t, _Op("GET", "webgrph/detected-apis", params={"page_url": page_url})
        )

    async def list_sessions(
        self, active_only: Optional[bool] = None
    ) -> List[Dict[str, Any]]:
        return await arun(
            self._t,
            _Op(
                "GET",
                "webgrph/sessions",
                params=compact({"active_only": active_only}),
                parse=as_list,
            ),
        )

    async def save_session(
        self,
        url: str,
        selected_nodes: Optional[List[Any]] = None,
        hierarchy_data: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
        last_crawl_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        return await arun(
            self._t,
            _ops_session(
                url, selected_nodes, hierarchy_data, session_id, last_crawl_id
            ),
        )

    async def get_session(self, session_id: str) -> Dict[str, Any]:
        return await arun(self._t, _Op("GET", f"webgrph/sessions/{session_id}"))

    async def delete_session(self, session_id: str) -> None:
        await arun(self._t, _Op("DELETE", f"webgrph/sessions/{session_id}"))

    async def end_session(self, session_id: str) -> Dict[str, Any]:
        return await arun(
            self._t, _Op("POST", f"webgrph/sessions/{session_id}/end", {})
        )

    async def update_session_job(self, session_id: str, job_id: str) -> Dict[str, Any]:
        return await arun(
            self._t,
            _Op(
                "PATCH", f"webgrph/sessions/{session_id}/job", params={"job_id": job_id}
            ),
        )

    async def get_dashboard_summary(self) -> Dict[str, Any]:
        return await arun(self._t, _Op("GET", "webgrph/analytics/dashboard/summary"))

    async def get_error_summary(self) -> Dict[str, Any]:
        return await arun(self._t, _Op("GET", "webgrph/analytics/error-summary"))

    async def get_job_trends(self) -> Dict[str, Any]:
        return await arun(self._t, _Op("GET", "webgrph/analytics/job-trends"))

    async def get_discovery_patterns(self) -> Dict[str, Any]:
        return await arun(
            self._t, _Op("GET", "webgrph/analytics/content/discovery-patterns")
        )

    async def get_efficiency_metrics(self) -> Dict[str, Any]:
        return await arun(
            self._t, _Op("GET", "webgrph/analytics/scraping/efficiency-metrics")
        )

    async def get_site_mapping_trends(self) -> Dict[str, Any]:
        return await arun(self._t, _Op("GET", "webgrph/analytics/site-maps/trends"))

    async def get_user_behavior_insights(self) -> Dict[str, Any]:
        return await arun(
            self._t, _Op("GET", "webgrph/analytics/users/behavior-insights")
        )
