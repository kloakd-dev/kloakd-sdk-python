"""
KLOAKD SDK — Webgrph module namespace.

Webgrph maps a site: a breadth-first crawl that builds its page hierarchy.
The API answers a crawl request with 202 and crawls in the background;
``crawl`` waits for it and loads every page node.

Usage::

    crawl = client.webgrph.crawl("https://example.com", max_depth=3)
    print(crawl.status, crawl.total_pages)
    site = client.skanyr.site_from_crawl(crawl.crawl_id)

A crawl can come back held (``crawl.held``: paused because the
organization's quota ran out; it resumes by itself on the same id) or
partial (``crawl.is_partial``; when ``crawl.resumable``,
``continue_crawl`` fetches the rest). ``wait_for_crawl(crawl_id)`` waits
for a crawl by its id. See ``CrawlResult``.

Crawl, extract and download in one job (added after 0.6.0)::

    job = client.webgrph.crawl_extract(
        "https://example.com", max_pages=200, extract={"fields": ["title", "price"]}
    )
    for row in client.webgrph.iter_crawl_extract_results(job.job_id):
        print(row.page_url, row.data)
    client.webgrph.download_crawl_extract(job.job_id, "rows.csv", format="csv")
"""

from __future__ import annotations

import asyncio
import time
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncIterator,
    Callable,
    Dict,
    Iterator,
    List,
    Optional,
)

from kloakd._download import (
    AsyncExportDownload,
    ExportDownload,
    asave_export,
    check_export_format,
    save_export,
)
from kloakd.errors import JobFailedError, JobTimeoutError
from kloakd.models import (
    CrawlContinueResult,
    CrawlEvent,
    CrawlExtractCancelResult,
    CrawlExtractCrawl,
    CrawlExtractJob,
    CrawlExtractPage,
    CrawlExtractPagesResult,
    CrawlExtractResultsPage,
    CrawlExtractRow,
    CrawlExtractStatus,
    CrawlResult,
    PageNode,
    SavedExport,
)
from kloakd.modules._ops import Op, _Op, arun, as_dict, as_list, compact, run, seg

if TYPE_CHECKING:
    from kloakd._http import _AsyncHttpTransport, _HttpTransport

_DEFAULT_POLL_TIMEOUT = 30 * 60.0
_DEFAULT_POLL_INTERVAL = 3.0
_FINISHED = ("completed", "failed", "cancelled")
#: A crawl paused because the organization's quota ran out (kobe-scraper
#: billing/held_work.py). Not an end: the crawl resumes on the same id.
_HELD = "held_quota"
#: The statuses a crawl waiter stops polling on.
_WAIT_ENDS = _FINISHED + (_HELD,)


def _node(p: Dict[str, Any]) -> PageNode:
    """A page node from the pages listing (kobe-scraper
    modules/webgrph/router.py HierarchyNodeResponse and its ``metadata``)."""
    meta = p.get("metadata") or {}
    return PageNode(
        url=p.get("url", ""),
        depth=int(p.get("depth") or 0),
        title=meta.get("title"),
        children=p.get("children_urls") or [],
        parent_url=p.get("parent_url"),
        is_grouping=bool(meta.get("is_grouping", False)),
        fetch_status=meta.get("fetch_status"),
        fetch_error=meta.get("fetch_error"),
    )


def _crawl_body(
    url: str,
    max_depth: Optional[int],
    max_pages: Optional[int],
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


#: Nodes per pages request the API accepts (modules/webgrph/router.py
#: PAGES_MAX_LIMIT); the API's own default is 100.
PAGES_MAX_LIMIT = 1000


def _pages_params(
    cursor: Optional[str], limit: int, include_grouping: bool = False
) -> Dict[str, Any]:
    """Query for ``GET webgrph/crawl/{id}/pages``. The API answers 422 for a
    ``limit`` outside 1-1000 or a cursor that is not a non-negative integer;
    both are checked here first."""
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise ValueError(f"limit must be an integer from 1 to {PAGES_MAX_LIMIT}")
    if not 1 <= limit <= PAGES_MAX_LIMIT:
        raise ValueError(
            f"limit must be from 1 to {PAGES_MAX_LIMIT}, got {limit}"
        )
    if cursor is not None and not str(cursor).isdigit():
        raise ValueError(
            "cursor must be a non-negative integer returned as next_cursor, "
            f"got {cursor!r}"
        )
    params = compact({"cursor": cursor, "limit": limit})
    if include_grouping:
        params["include_grouping"] = "true"
    return params


def _opt_bool(value: Any) -> Optional[bool]:
    return bool(value) if value is not None else None


def _result(
    status: Dict[str, Any], url: str, pages: List[PageNode], error: Optional[str] = None
) -> CrawlResult:
    """A CrawlResult from a crawl's status body (kobe-scraper
    modules/webgrph/router.py CrawlStatusResponse, which has no ``url``)."""
    state = str(status.get("status") or "")
    held = state == _HELD
    pages_discovered = status.get("pages_discovered")
    pages_fetched = status.get("pages_fetched")
    pages_unfetched = status.get("pages_unfetched")
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
        # A held crawl has not failed: its message is not an error.
        error=None if held else error or status.get("error"),
        status=state,
        is_partial=_opt_bool(status.get("is_partial")),
        partial_reason=status.get("partial_reason"),
        resumable=_opt_bool(status.get("resumable")),
        pages_discovered=(
            int(pages_discovered) if pages_discovered is not None else None
        ),
        pages_fetched=int(pages_fetched) if pages_fetched is not None else None,
        pages_unfetched=(
            int(pages_unfetched) if pages_unfetched is not None else None
        ),
        error_code=status.get("error_code"),
        message=status.get("message"),
        held=held,
    )


def _with_id(status: Dict[str, Any], crawl_id: str) -> Dict[str, Any]:
    return {**status, "crawl_id": status.get("crawl_id") or crawl_id}


def _still_running(status: Dict[str, Any], url: str, timeout: float) -> CrawlResult:
    return _result(
        status,
        url,
        [],
        error=f"Crawl {status.get('crawl_id')} still running after {timeout}s",
    )


def _without_pages(status: Dict[str, Any], url: str) -> Optional[CrawlResult]:
    """The result of a crawl a waiter stopped on that has no pages to load:
    held (no error) or failed/cancelled (``error`` set). None for a
    completed crawl, whose pages the caller loads."""
    state = status.get("status")
    if state == "completed":
        return None
    if state == _HELD:
        return _result(status, url, [])
    return _result(status, url, [], error=status.get("error") or f"Crawl {state}")


def _continued(crawl_id: str) -> Callable[[Any], CrawlContinueResult]:
    def parse(body: Any) -> CrawlContinueResult:
        raw = as_dict(body)
        return CrawlContinueResult(
            success=bool(raw.get("success", False)),
            crawl_id=str(raw.get("crawl_id") or crawl_id),
            status=str(raw.get("status") or ""),
        )

    return parse


def _ops_continue(crawl_id: str) -> Op[CrawlContinueResult]:
    return _Op(
        "POST",
        f"webgrph/crawl/{seg(crawl_id)}/continue",
        {},
        parse=_continued(crawl_id),
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
        status=data.get("status"),
        message=data.get("message"),
        error=data.get("error"),
        sequence=data.get("sequence"),
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


# ── Crawl-extract (kobe-scraper modules/webgrph/crawl_extract_router.py) ──

#: Rows or pages per request the API accepts (1-1000; its default is 100).
CRAWL_EXTRACT_MAX_LIMIT = 1000
_CRAWL_EXTRACT_POLL_TIMEOUT = 60 * 60.0
_CE = "webgrph/crawl-extract"


def _opt_int(value: Any) -> Optional[int]:
    return int(value) if value is not None else None


def _ce_limit(limit: Optional[int]) -> None:
    """The API answers 422 for a ``limit`` outside 1-1000; checked here first."""
    if limit is None:
        return
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise ValueError(
            f"limit must be an integer from 1 to {CRAWL_EXTRACT_MAX_LIMIT}"
        )
    if not 1 <= limit <= CRAWL_EXTRACT_MAX_LIMIT:
        raise ValueError(
            f"limit must be from 1 to {CRAWL_EXTRACT_MAX_LIMIT}, got {limit}"
        )


def _ce_job(url: str) -> Callable[[Any], CrawlExtractJob]:
    def parse(body: Any) -> CrawlExtractJob:
        raw = as_dict(body)
        limits = raw.get("limits") or {}
        return CrawlExtractJob(
            job_id=str(raw.get("job_id") or ""),
            crawl_id=str(raw.get("crawl_id") or ""),
            url=str(raw.get("url") or url),
            status=str(raw.get("status") or ""),
            max_pages=_opt_int(limits.get("max_pages")),
            max_depth=_opt_int(limits.get("max_depth")),
            links=raw.get("links") or {},
        )

    return parse


def _ce_crawl(raw: Any) -> Optional[CrawlExtractCrawl]:
    """The status body's ``crawl`` object (kobe-scraper
    modules/webgrph/crawl_extract.py crawl_truth); None when it is null."""
    if not isinstance(raw, dict):
        return None
    return CrawlExtractCrawl(
        status=raw.get("status"),
        is_partial=_opt_bool(raw.get("is_partial")),
        partial_reason=raw.get("partial_reason"),
        pages_discovered=_opt_int(raw.get("pages_discovered")),
        pages_fetched=_opt_int(raw.get("pages_fetched")),
        pages_unfetched=_opt_int(raw.get("pages_unfetched")),
        cancelled=bool(raw.get("cancelled", False)),
        root_unfetched=bool(raw.get("root_unfetched", False)),
        error=raw.get("error"),
        error_code=raw.get("error_code"),
    )


def _ce_status(job_id: str) -> Callable[[Any], CrawlExtractStatus]:
    def parse(body: Any) -> CrawlExtractStatus:
        raw = as_dict(body)
        progress = raw.get("progress") or {}
        return CrawlExtractStatus(
            job_id=str(raw.get("job_id") or job_id),
            status=str(raw.get("status") or ""),
            crawl_id=str(raw.get("crawl_id") or ""),
            url=str(raw.get("url") or ""),
            cancel_requested=bool(raw.get("cancel_requested", False)),
            pages_crawled=int(progress.get("pages_crawled") or 0),
            pages_total=_opt_int(progress.get("pages_total")),
            pages_extracted=int(progress.get("pages_extracted") or 0),
            pages_failed=int(progress.get("pages_failed") or 0),
            items=int(progress.get("items") or 0),
            error=raw.get("error"),
            error_code=raw.get("error_code"),
            request=raw.get("request") or {},
            created_at=raw.get("created_at"),
            started_at=raw.get("started_at"),
            completed_at=raw.get("completed_at"),
            updated_at=raw.get("updated_at"),
            links=raw.get("links") or {},
            pages_by_method=raw.get("pages_by_method") or {},
            shapes=raw.get("shapes") or [],
            crawl=_ce_crawl(raw.get("crawl")),
        )

    return parse


def _ce_results(job_id: str) -> Callable[[Any], CrawlExtractResultsPage]:
    def parse(body: Any) -> CrawlExtractResultsPage:
        raw = as_dict(body)
        rows = [
            CrawlExtractRow(
                page_url=str(r.get("page_url") or ""),
                row_kind=str(r.get("row_kind") or ""),
                item_index=int(r.get("item_index") or 0),
                data=r.get("data") or {},
                page_type=r.get("page_type"),
                shape=r.get("shape"),
            )
            for r in raw.get("rows") or []
        ]
        return CrawlExtractResultsPage(
            job_id=str(raw.get("job_id") or job_id),
            status=str(raw.get("status") or ""),
            total=int(raw.get("total") or 0),
            count=int(raw.get("count") or len(rows)),
            rows=rows,
            next_cursor=raw.get("next_cursor") or None,
        )

    return parse


def _ce_pages(job_id: str) -> Callable[[Any], CrawlExtractPagesResult]:
    def parse(body: Any) -> CrawlExtractPagesResult:
        raw = as_dict(body)
        pages = [
            CrawlExtractPage(
                page_seq=int(p.get("page_seq") or 0),
                page_url=str(p.get("page_url") or ""),
                status=str(p.get("status") or ""),
                page_type=p.get("page_type"),
                title=p.get("title"),
                method=p.get("method"),
                item_count=int(p.get("item_count") or 0),
                detail=p.get("detail"),
                extracted_at=p.get("extracted_at"),
            )
            for p in raw.get("pages") or []
        ]
        return CrawlExtractPagesResult(
            job_id=str(raw.get("job_id") or job_id),
            status=str(raw.get("status") or ""),
            count=int(raw.get("count") or len(pages)),
            offset=int(raw.get("offset") or 0),
            pages=pages,
        )

    return parse


def _ce_cancelled(job_id: str) -> Callable[[Any], CrawlExtractCancelResult]:
    def parse(body: Any) -> CrawlExtractCancelResult:
        raw = as_dict(body)
        return CrawlExtractCancelResult(
            success=bool(raw.get("success", False)),
            job_id=str(raw.get("job_id") or job_id),
            crawl_id=str(raw.get("crawl_id") or ""),
            status=str(raw.get("status") or ""),
        )

    return parse


def _ops_ce_start(
    url: str,
    max_depth: Optional[int],
    max_pages: Optional[int],
    include_external_links: Optional[bool],
    session_artifact_id: Optional[str],
    capture_mode: Optional[str],
    scope: Optional[Dict[str, Any]],
    budget: Optional[Dict[str, Any]],
    extract: Optional[Dict[str, Any]],
) -> Op[CrawlExtractJob]:
    return _Op(
        "POST",
        _CE,
        compact(
            {
                "url": url,
                "max_depth": max_depth,
                "max_pages": max_pages,
                "include_external_links": include_external_links,
                "session_artifact_id": session_artifact_id,
                "capture_mode": capture_mode,
                "scope": scope,
                "budget": budget,
                "extract": extract,
            }
        ),
        parse=_ce_job(url),
    )


def _ops_ce_get(job_id: str) -> Op[CrawlExtractStatus]:
    return _Op("GET", f"{_CE}/{seg(job_id)}", parse=_ce_status(job_id))


def _ops_ce_results(
    job_id: str,
    limit: Optional[int],
    cursor: Optional[str],
    shape: Optional[str],
    page_type: Optional[str],
    kind: Optional[str],
) -> Op[CrawlExtractResultsPage]:
    _ce_limit(limit)
    return _Op(
        "GET",
        f"{_CE}/{seg(job_id)}/results",
        params=compact(
            {
                "limit": limit,
                "cursor": cursor,
                "shape": shape,
                "page_type": page_type,
                "kind": kind,
            }
        ),
        parse=_ce_results(job_id),
    )


def _ops_ce_pages(
    job_id: str, limit: Optional[int], offset: Optional[int], status: Optional[str]
) -> Op[CrawlExtractPagesResult]:
    _ce_limit(limit)
    return _Op(
        "GET",
        f"{_CE}/{seg(job_id)}/pages",
        params=compact({"limit": limit, "offset": offset, "status": status}),
        parse=_ce_pages(job_id),
    )


def _ops_ce_cancel(job_id: str) -> Op[CrawlExtractCancelResult]:
    return _Op(
        "POST", f"{_CE}/{seg(job_id)}/cancel", {}, parse=_ce_cancelled(job_id)
    )


def _ce_export_params(
    format: str, shape: Optional[str], page_type: Optional[str], kind: Optional[str]
) -> Dict[str, Any]:
    return compact(
        {
            "format": check_export_format(format),
            "shape": shape,
            "page_type": page_type,
            "kind": kind,
        }
    )


def _ce_still_running(job_id: str, timeout: float) -> JobTimeoutError:
    return JobTimeoutError(
        f"Crawl-extract job {job_id} still running after {timeout}s; "
        "check it with get_crawl_extract",
        job_id,
    )


def _ce_ended(status: CrawlExtractStatus) -> CrawlExtractStatus:
    if status.status == "failed":
        raise JobFailedError(status.error or "Crawl-extract job failed", status.job_id)
    return status


class WebgrphNamespace:
    """Synchronous Webgrph operations. Access via ``client.webgrph``."""

    def __init__(self, transport: "_HttpTransport") -> None:
        self._t = transport

    def start_crawl(
        self,
        url: str,
        max_depth: Optional[int] = None,
        max_pages: Optional[int] = None,
        include_external_links: bool = False,
        session_artifact_id: Optional[str] = None,
        fast_mode: Optional[bool] = None,
        capture_mode: Optional[str] = None,
        scope: Optional[Dict[str, Any]] = None,
        budget: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Start a crawl (the API answers 202); returns its crawl id.

        ``max_depth`` and ``max_pages`` are sent only when given; left out,
        the API uses the plan's default (the SDK no longer sends 3 and 100).
        """
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
        max_depth: Optional[int] = None,
        max_pages: Optional[int] = None,
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
        Crawl a site: start it, wait until it ends, and load every page
        node. See ``wait_for_crawl`` for what comes back; in short:

        * completed: ``success`` True and ``pages`` loaded. It can still be
          partial (``is_partial``); when ``resumable``, ``continue_crawl``
          fetches the rest.
        * held for quota: ``held`` True, ``status == "held_quota"``,
          ``message`` set, ``error`` None, no pages. Not an error and not
          raised: the crawl resumes by itself. Call
          ``wait_for_crawl(result.crawl_id)`` again later.
        * failed, cancelled, or still running after ``poll_timeout``:
          ``success`` False and ``error`` set.

        ``max_depth`` and ``max_pages`` are sent only when given; left out,
        the API uses the plan's default. With ``wait=False`` only the crawl
        id is returned (the SDK sets ``status`` to "queued"; the start
        answer carries no status).
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
        return self.wait_for_crawl(crawl_id, poll_timeout, poll_interval, url=url)

    def wait_for_crawl(
        self,
        crawl_id: str,
        poll_timeout: float = _DEFAULT_POLL_TIMEOUT,
        poll_interval: float = _DEFAULT_POLL_INTERVAL,
        url: str = "",
    ) -> CrawlResult:
        """Wait for a crawl by its id and load its page nodes.

        Polls ``get_crawl_status`` until the crawl is completed, failed,
        cancelled or held, and never raises for any of those:

        * completed: ``success`` True, ``pages`` loaded, the outcome fields
          set (``is_partial``, ``partial_reason``, ``resumable``,
          ``pages_discovered``, ``pages_fetched``, ``pages_unfetched``).
        * held (``status == "held_quota"``): ``held`` True, ``success``
          False, ``error`` None, ``message`` the server's text, no pages
          loaded. The crawl is paused because the organization's quota ran
          out. It keeps its id and resumes by itself when quota returns (an
          upgrade, a top-up or a new billing period); after 30 days held it
          ends ``failed`` with ``error_code == "held_quota_expired"``. Call
          this method again later with the same id.
        * failed or cancelled: ``success`` False, ``error`` set.
        * still running after ``poll_timeout`` seconds: ``success`` False,
          ``error`` says so; the crawl carries on.

        Use it after ``crawl(..., wait=False)``, after a held result, and
        after ``continue_crawl``.

        Args:
            crawl_id: The crawl.
            poll_timeout: Seconds to wait.
            poll_interval: Seconds between two looks.
            url: The crawl's URL, to have it on the result (the status
                answer carries none; empty when not given).
        """
        deadline = time.monotonic() + poll_timeout
        status = _with_id(self.get_crawl_status(crawl_id), crawl_id)
        while status.get("status") not in _WAIT_ENDS:
            if time.monotonic() + poll_interval > deadline:
                return _still_running(status, url, poll_timeout)
            time.sleep(poll_interval)
            status = _with_id(self.get_crawl_status(crawl_id), crawl_id)
        ended = _without_pages(status, url)
        if ended is not None:
            return ended
        return _result(status, url, self.crawl_all_pages(crawl_id))

    def continue_crawl(self, crawl_id: str) -> CrawlContinueResult:
        """Continue a crawl that ended partial at its time budget.

        Only for a crawl that has ended and whose ``resumable`` is True.
        The crawl goes back to ``queued`` on the same id and fetches the
        pages it left, with a new time budget; pages already fetched are
        not fetched again. Then wait by id again::

            crawl = client.webgrph.crawl(url)
            if crawl.resumable:
                client.webgrph.continue_crawl(crawl.crawl_id)
                crawl = client.webgrph.wait_for_crawl(crawl.crawl_id, url=url)

        Raises:
            ApiError: 409 when the crawl is not one that stopped at its time
                budget (an unknown crawl id included), has not ended, or is
                already being continued. The quota checks of a new crawl
                apply too (their errors are the ones ``crawl`` raises).
        """
        return run(self._t, _ops_continue(crawl_id))

    def crawl_all(self, url: str, **kwargs: Any) -> List[PageNode]:
        """Every page node of a completed crawl (same options as ``crawl``).

        Returns an empty list, without raising, when the crawl did not
        complete: failed, cancelled, still running at ``poll_timeout``, or
        held for quota. The list alone cannot tell these apart, and it does
        not say whether the crawl was partial; call ``crawl`` for that.
        """
        return self.crawl(url, **kwargs).pages

    def crawl_stream(
        self,
        url: str,
        max_depth: Optional[int] = None,
        max_pages: Optional[int] = None,
        include_external_links: bool = False,
        session_artifact_id: Optional[str] = None,
    ) -> Iterator[CrawlEvent]:
        """Start a crawl and yield its progress events (Server-Sent Events).

        The stream ends when the crawl is completed, failed, cancelled or
        held for quota. ``max_depth`` and ``max_pages`` are sent only when
        given."""
        crawl_id = self.start_crawl(
            url, max_depth, max_pages, include_external_links, session_artifact_id
        )
        for data in self.crawl_events(crawl_id):
            yield _event(data, crawl_id)

    def get_crawl_status(self, crawl_id: str) -> Dict[str, Any]:
        return run(self._t, _Op("GET", f"webgrph/crawl/{seg(crawl_id)}"))

    def cancel_crawl(self, crawl_id: str) -> Dict[str, Any]:
        return run(self._t, _Op("POST", f"webgrph/crawl/{seg(crawl_id)}/cancel", {}))

    def crawl_events(
        self, crawl_id: str, last_sequence: Optional[int] = None
    ) -> Iterator[Dict[str, Any]]:
        """A crawl's progress events; ``last_sequence`` resumes after an event already seen."""
        params = {"last_sequence": last_sequence} if last_sequence is not None else None
        for _name, data in self._t.iter_sse(
            "GET", f"webgrph/crawl/{seg(crawl_id)}/events", params=params
        ):
            yield data

    def get_crawl_pages(
        self,
        crawl_id: str,
        cursor: Optional[str] = None,
        limit: int = 500,
        include_grouping: bool = False,
    ) -> Dict[str, Any]:
        """One page of a crawl's hierarchy: ``nodes``, ``next_cursor``, ``total``.

        Only fetched pages are listed, each under the page the crawl found
        it on, so ``total`` matches the crawl's ``total_pages``.

        Args:
            crawl_id: The crawl.
            cursor: ``next_cursor`` from the previous page (a non-negative
                integer as a string); None for the first page.
            limit: Nodes per page, 1-1000 (the SDK's default 500).
            include_grouping: Also list the tree's grouping folders
                (``metadata.is_grouping``), which were never fetched (new in
                0.6.0).

        Raises:
            ValueError: ``limit`` is outside 1-1000 or ``cursor`` is not a
                non-negative integer (the API would answer 422).
        """
        return run(
            self._t,
            _Op(
                "GET",
                f"webgrph/crawl/{seg(crawl_id)}/pages",
                params=_pages_params(cursor, limit, include_grouping),
            ),
        )

    def crawl_all_pages(
        self, crawl_id: str, include_grouping: bool = False, limit: int = 500
    ) -> List[PageNode]:
        """Every page node of a crawl, following the cursor (fetched pages
        only unless ``include_grouping``)."""
        nodes: List[PageNode] = []
        cursor: Optional[str] = None
        while True:
            page = self.get_crawl_pages(
                crawl_id, cursor=cursor, limit=limit, include_grouping=include_grouping
            )
            nodes.extend(_node(n) for n in page.get("nodes") or [])
            cursor = page.get("next_cursor")
            if not cursor:
                return nodes

    # ── Crawl, extract and download in one job (added after 0.6.0) ──

    def start_crawl_extract(
        self,
        url: str,
        max_depth: Optional[int] = None,
        max_pages: Optional[int] = None,
        include_external_links: Optional[bool] = None,
        session_artifact_id: Optional[str] = None,
        capture_mode: Optional[str] = None,
        scope: Optional[Dict[str, Any]] = None,
        budget: Optional[Dict[str, Any]] = None,
        extract: Optional[Dict[str, Any]] = None,
    ) -> CrawlExtractJob:
        """Start a job that crawls a site and extracts every page it
        fetches (the API answers 202). Read it with ``get_crawl_extract``,
        its rows with ``get_crawl_extract_results`` or an export.

        Args:
            url: Where the crawl starts.
            max_depth, max_pages: Crawl limits; the plan's cap applies.
            extract: What to extract: ``{"entity_type": ...}``,
                ``{"fields": ["title", "price"]}`` or ``{"schema":
                {"item_selector": ..., "fields": [{"name", "selector",
                "attribute", "type"}]}}``. Without it the API decides per
                page.

        Raises:
            ForbiddenError: a test key (``test_key_not_allowed``), or the
                plan has no Kolektr (``module_not_entitled``).
        """
        return run(
            self._t,
            _ops_ce_start(
                url,
                max_depth,
                max_pages,
                include_external_links,
                session_artifact_id,
                capture_mode,
                scope,
                budget,
                extract,
            ),
        )

    def get_crawl_extract(self, job_id: str) -> CrawlExtractStatus:
        """A job's state, progress and the row shapes found so far. An
        unknown job raises ApiError 404."""
        return run(self._t, _ops_ce_get(job_id))

    def wait_for_crawl_extract(
        self,
        job_id: str,
        poll_interval: float = _DEFAULT_POLL_INTERVAL,
        poll_timeout: float = _CRAWL_EXTRACT_POLL_TIMEOUT,
    ) -> CrawlExtractStatus:
        """Poll a job until it ends; returns its last state (completed,
        failed or cancelled: check ``ok``). Still running after
        ``poll_timeout`` seconds raises JobTimeoutError; the job carries on.

        A job whose crawl is held for quota (``crawl.status ==
        "held_quota"``) is returned at once with ``held`` True and
        ``finished`` False, instead of being polled to the timeout: the
        crawl is paused because the organization's quota ran out, it
        resumes by itself when quota returns, and the job then carries on
        (after 30 days held the crawl ends failed with
        ``held_quota_expired``). Call this method again later."""
        deadline = time.monotonic() + poll_timeout
        while True:
            status = self.get_crawl_extract(job_id)
            if status.finished or status.held:
                return status
            if time.monotonic() + poll_interval > deadline:
                raise _ce_still_running(job_id, poll_timeout)
            time.sleep(poll_interval)

    def crawl_extract(
        self,
        url: str,
        max_depth: Optional[int] = None,
        max_pages: Optional[int] = None,
        include_external_links: Optional[bool] = None,
        session_artifact_id: Optional[str] = None,
        capture_mode: Optional[str] = None,
        scope: Optional[Dict[str, Any]] = None,
        budget: Optional[Dict[str, Any]] = None,
        extract: Optional[Dict[str, Any]] = None,
        poll_interval: float = _DEFAULT_POLL_INTERVAL,
        poll_timeout: float = _CRAWL_EXTRACT_POLL_TIMEOUT,
    ) -> CrawlExtractStatus:
        """Crawl a site and extract every page: start the job and wait until
        it ends; returns its last state (completed or cancelled), or the
        state of a job whose crawl is held for quota (``held`` True,
        ``finished`` False: see ``wait_for_crawl_extract``).

        Raises:
            JobFailedError: the job failed (the rows it wrote can still be
                read and exported with the error's ``job_id``).
            JobTimeoutError: still running after ``poll_timeout`` seconds;
                the job carries on.
        """
        job = self.start_crawl_extract(
            url,
            max_depth,
            max_pages,
            include_external_links,
            session_artifact_id,
            capture_mode,
            scope,
            budget,
            extract,
        )
        return _ce_ended(
            self.wait_for_crawl_extract(job.job_id, poll_interval, poll_timeout)
        )

    def get_crawl_extract_results(
        self,
        job_id: str,
        limit: Optional[int] = None,
        cursor: Optional[str] = None,
        shape: Optional[str] = None,
        page_type: Optional[str] = None,
        kind: Optional[str] = None,
    ) -> CrawlExtractResultsPage:
        """One page of a job's rows, in page order then item order; pass
        ``next_cursor`` back as ``cursor`` for the next. Rows appear while
        the job runs.

        Args:
            limit: Rows per page, 1-1000 (the API's default is 100).
            shape, page_type: Only rows of that shape or page type.
            kind: ``"item"`` or ``"page"`` rows only.

        Raises:
            ValueError: ``limit`` is outside 1-1000 (the API would answer 422).
        """
        return run(
            self._t, _ops_ce_results(job_id, limit, cursor, shape, page_type, kind)
        )

    def iter_crawl_extract_results(
        self,
        job_id: str,
        limit: Optional[int] = None,
        shape: Optional[str] = None,
        page_type: Optional[str] = None,
        kind: Optional[str] = None,
    ) -> Iterator[CrawlExtractRow]:
        """Every row of a job, one page at a time, following the cursor."""
        cursor: Optional[str] = None
        while True:
            page = self.get_crawl_extract_results(
                job_id, limit, cursor, shape, page_type, kind
            )
            yield from page.rows
            cursor = page.next_cursor
            if not cursor:
                return

    def crawl_extract_all_results(
        self,
        job_id: str,
        limit: Optional[int] = None,
        shape: Optional[str] = None,
        page_type: Optional[str] = None,
        kind: Optional[str] = None,
    ) -> List[CrawlExtractRow]:
        """Every row of a job in memory (for a large job prefer
        ``iter_crawl_extract_results`` or an export)."""
        return list(
            self.iter_crawl_extract_results(job_id, limit, shape, page_type, kind)
        )

    def get_crawl_extract_pages(
        self,
        job_id: str,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        status: Optional[str] = None,
    ) -> CrawlExtractPagesResult:
        """The job's pages and what each extraction came to (``status``:
        ``"extracted"`` or ``"failed"`` pages only). ``limit`` is 1-1000."""
        return run(self._t, _ops_ce_pages(job_id, limit, offset, status))

    def export_crawl_extract(
        self,
        job_id: str,
        format: str = "json",
        shape: Optional[str] = None,
        page_type: Optional[str] = None,
        kind: Optional[str] = None,
    ) -> ExportDownload:
        """A job's rows as a streamed file (``format``: json, ndjson or csv;
        the CSV starts with a UTF-8 byte order mark). A job that has not
        completed exports the rows it has (``job_status``, from the
        ``X-Job-Status`` header). ``crawl`` says what the job's crawl did,
        from the ``X-Crawl-*`` headers (``status``, ``is_partial``,
        ``partial_reason``, ``pages_discovered``, ``pages_fetched``,
        ``pages_unfetched``, ``cancelled``, ``root_unfetched``; each None
        when its header was not sent, the whole object None when none
        was). Close the result, or use it as a context manager.

        Raises:
            ValueError: ``format`` is not json, ndjson or csv.
        """
        response, client = self._t.open_stream(
            f"{_CE}/{seg(job_id)}/export",
            _ce_export_params(format, shape, page_type, kind),
        )
        return ExportDownload(response, client)

    def download_crawl_extract(
        self,
        job_id: str,
        path: str,
        format: str = "json",
        shape: Optional[str] = None,
        page_type: Optional[str] = None,
        kind: Optional[str] = None,
    ) -> SavedExport:
        """Write a job's rows to the file ``path`` as they arrive. The file
        is created once the API has answered 200. The result carries
        ``job_status`` and ``crawl`` as ``export_crawl_extract`` does."""
        return save_export(
            self.export_crawl_extract(job_id, format, shape, page_type, kind), path
        )

    def cancel_crawl_extract(self, job_id: str) -> CrawlExtractCancelResult:
        """Stop a job; rows already written stay. ``status`` is
        ``cancelled``, or ``cancelling`` while a worker still holds it. A
        job that has already ended raises ApiError 409."""
        return run(self._t, _ops_ce_cancel(job_id))

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

    def list_sessions(self, active_only: bool = True) -> List[Dict[str, Any]]:
        return run(
            self._t,
            _Op(
                "GET",
                "webgrph/sessions",
                params={"active_only": "true" if active_only else "false"},
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
        return run(self._t, _Op("GET", f"webgrph/sessions/{seg(session_id)}"))

    def delete_session(self, session_id: str) -> None:
        run(self._t, _Op("DELETE", f"webgrph/sessions/{seg(session_id)}"))

    def end_session(self, session_id: str) -> Dict[str, Any]:
        return run(self._t, _Op("POST", f"webgrph/sessions/{seg(session_id)}/end", {}))

    def update_session_job(self, session_id: str, job_id: str) -> Dict[str, Any]:
        return run(
            self._t,
            _Op(
                "PATCH", f"webgrph/sessions/{seg(session_id)}/job", params={"job_id": job_id}
            ),
        )


class AsyncWebgrphNamespace:
    """Async Webgrph operations. Access via ``async_client.webgrph``."""

    def __init__(self, transport: "_AsyncHttpTransport") -> None:
        self._t = transport

    async def start_crawl(
        self,
        url: str,
        max_depth: Optional[int] = None,
        max_pages: Optional[int] = None,
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
        max_depth: Optional[int] = None,
        max_pages: Optional[int] = None,
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
        return await self.wait_for_crawl(
            crawl_id, poll_timeout, poll_interval, url=url
        )

    async def wait_for_crawl(
        self,
        crawl_id: str,
        poll_timeout: float = _DEFAULT_POLL_TIMEOUT,
        poll_interval: float = _DEFAULT_POLL_INTERVAL,
        url: str = "",
    ) -> CrawlResult:
        """Async equivalent of WebgrphNamespace.wait_for_crawl: a crawl held
        for quota comes back with ``held`` True (not raised, no pages)."""
        deadline = time.monotonic() + poll_timeout
        status = _with_id(await self.get_crawl_status(crawl_id), crawl_id)
        while status.get("status") not in _WAIT_ENDS:
            if time.monotonic() + poll_interval > deadline:
                return _still_running(status, url, poll_timeout)
            await asyncio.sleep(poll_interval)
            status = _with_id(await self.get_crawl_status(crawl_id), crawl_id)
        ended = _without_pages(status, url)
        if ended is not None:
            return ended
        return _result(status, url, await self.crawl_all_pages(crawl_id))

    async def continue_crawl(self, crawl_id: str) -> CrawlContinueResult:
        """Async equivalent of WebgrphNamespace.continue_crawl."""
        return await arun(self._t, _ops_continue(crawl_id))

    async def crawl_all(self, url: str, **kwargs: Any) -> List[PageNode]:
        """Async equivalent of WebgrphNamespace.crawl_all: an empty list
        when the crawl did not complete (held for quota included)."""
        return (await self.crawl(url, **kwargs)).pages

    async def crawl_stream(
        self,
        url: str,
        max_depth: Optional[int] = None,
        max_pages: Optional[int] = None,
        include_external_links: bool = False,
        session_artifact_id: Optional[str] = None,
    ) -> AsyncIterator[CrawlEvent]:
        """Start a crawl and yield its progress events (Server-Sent Events).

        The stream ends when the crawl is completed, failed, cancelled or
        held for quota. ``max_depth`` and ``max_pages`` are sent only when
        given."""
        crawl_id = await self.start_crawl(
            url, max_depth, max_pages, include_external_links, session_artifact_id
        )
        async for data in self.crawl_events(crawl_id):
            yield _event(data, crawl_id)

    async def get_crawl_status(self, crawl_id: str) -> Dict[str, Any]:
        return await arun(self._t, _Op("GET", f"webgrph/crawl/{seg(crawl_id)}"))

    async def cancel_crawl(self, crawl_id: str) -> Dict[str, Any]:
        return await arun(self._t, _Op("POST", f"webgrph/crawl/{seg(crawl_id)}/cancel", {}))

    async def crawl_events(
        self, crawl_id: str, last_sequence: Optional[int] = None
    ) -> AsyncIterator[Dict[str, Any]]:
        params = {"last_sequence": last_sequence} if last_sequence is not None else None
        async for _name, data in self._t.aiter_sse(
            "GET", f"webgrph/crawl/{seg(crawl_id)}/events", params=params
        ):
            yield data

    async def get_crawl_pages(
        self,
        crawl_id: str,
        cursor: Optional[str] = None,
        limit: int = 500,
        include_grouping: bool = False,
    ) -> Dict[str, Any]:
        """Async equivalent of WebgrphNamespace.get_crawl_pages."""
        return await arun(
            self._t,
            _Op(
                "GET",
                f"webgrph/crawl/{seg(crawl_id)}/pages",
                params=_pages_params(cursor, limit, include_grouping),
            ),
        )

    async def crawl_all_pages(
        self, crawl_id: str, include_grouping: bool = False, limit: int = 500
    ) -> List[PageNode]:
        """Async equivalent of WebgrphNamespace.crawl_all_pages."""
        nodes: List[PageNode] = []
        cursor: Optional[str] = None
        while True:
            page = await self.get_crawl_pages(
                crawl_id, cursor=cursor, limit=limit, include_grouping=include_grouping
            )
            nodes.extend(_node(n) for n in page.get("nodes") or [])
            cursor = page.get("next_cursor")
            if not cursor:
                return nodes

    # ── Crawl, extract and download in one job (added after 0.6.0) ──

    async def start_crawl_extract(
        self,
        url: str,
        max_depth: Optional[int] = None,
        max_pages: Optional[int] = None,
        include_external_links: Optional[bool] = None,
        session_artifact_id: Optional[str] = None,
        capture_mode: Optional[str] = None,
        scope: Optional[Dict[str, Any]] = None,
        budget: Optional[Dict[str, Any]] = None,
        extract: Optional[Dict[str, Any]] = None,
    ) -> CrawlExtractJob:
        """Async equivalent of WebgrphNamespace.start_crawl_extract."""
        return await arun(
            self._t,
            _ops_ce_start(
                url,
                max_depth,
                max_pages,
                include_external_links,
                session_artifact_id,
                capture_mode,
                scope,
                budget,
                extract,
            ),
        )

    async def get_crawl_extract(self, job_id: str) -> CrawlExtractStatus:
        """Async equivalent of WebgrphNamespace.get_crawl_extract."""
        return await arun(self._t, _ops_ce_get(job_id))

    async def wait_for_crawl_extract(
        self,
        job_id: str,
        poll_interval: float = _DEFAULT_POLL_INTERVAL,
        poll_timeout: float = _CRAWL_EXTRACT_POLL_TIMEOUT,
    ) -> CrawlExtractStatus:
        """Async equivalent of WebgrphNamespace.wait_for_crawl_extract."""
        deadline = time.monotonic() + poll_timeout
        while True:
            status = await self.get_crawl_extract(job_id)
            if status.finished or status.held:
                return status
            if time.monotonic() + poll_interval > deadline:
                raise _ce_still_running(job_id, poll_timeout)
            await asyncio.sleep(poll_interval)

    async def crawl_extract(
        self,
        url: str,
        max_depth: Optional[int] = None,
        max_pages: Optional[int] = None,
        include_external_links: Optional[bool] = None,
        session_artifact_id: Optional[str] = None,
        capture_mode: Optional[str] = None,
        scope: Optional[Dict[str, Any]] = None,
        budget: Optional[Dict[str, Any]] = None,
        extract: Optional[Dict[str, Any]] = None,
        poll_interval: float = _DEFAULT_POLL_INTERVAL,
        poll_timeout: float = _CRAWL_EXTRACT_POLL_TIMEOUT,
    ) -> CrawlExtractStatus:
        """Async equivalent of WebgrphNamespace.crawl_extract."""
        job = await self.start_crawl_extract(
            url,
            max_depth,
            max_pages,
            include_external_links,
            session_artifact_id,
            capture_mode,
            scope,
            budget,
            extract,
        )
        return _ce_ended(
            await self.wait_for_crawl_extract(job.job_id, poll_interval, poll_timeout)
        )

    async def get_crawl_extract_results(
        self,
        job_id: str,
        limit: Optional[int] = None,
        cursor: Optional[str] = None,
        shape: Optional[str] = None,
        page_type: Optional[str] = None,
        kind: Optional[str] = None,
    ) -> CrawlExtractResultsPage:
        """Async equivalent of WebgrphNamespace.get_crawl_extract_results."""
        return await arun(
            self._t, _ops_ce_results(job_id, limit, cursor, shape, page_type, kind)
        )

    async def iter_crawl_extract_results(
        self,
        job_id: str,
        limit: Optional[int] = None,
        shape: Optional[str] = None,
        page_type: Optional[str] = None,
        kind: Optional[str] = None,
    ) -> AsyncIterator[CrawlExtractRow]:
        """Async equivalent of WebgrphNamespace.iter_crawl_extract_results."""
        cursor: Optional[str] = None
        while True:
            page = await self.get_crawl_extract_results(
                job_id, limit, cursor, shape, page_type, kind
            )
            for row in page.rows:
                yield row
            cursor = page.next_cursor
            if not cursor:
                return

    async def crawl_extract_all_results(
        self,
        job_id: str,
        limit: Optional[int] = None,
        shape: Optional[str] = None,
        page_type: Optional[str] = None,
        kind: Optional[str] = None,
    ) -> List[CrawlExtractRow]:
        """Async equivalent of WebgrphNamespace.crawl_extract_all_results."""
        return [
            row
            async for row in self.iter_crawl_extract_results(
                job_id, limit, shape, page_type, kind
            )
        ]

    async def get_crawl_extract_pages(
        self,
        job_id: str,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        status: Optional[str] = None,
    ) -> CrawlExtractPagesResult:
        """Async equivalent of WebgrphNamespace.get_crawl_extract_pages."""
        return await arun(self._t, _ops_ce_pages(job_id, limit, offset, status))

    async def export_crawl_extract(
        self,
        job_id: str,
        format: str = "json",
        shape: Optional[str] = None,
        page_type: Optional[str] = None,
        kind: Optional[str] = None,
    ) -> AsyncExportDownload:
        """Async equivalent of WebgrphNamespace.export_crawl_extract; close
        the result with ``aclose`` or use it with ``async with``."""
        response, client = await self._t.open_stream(
            f"{_CE}/{seg(job_id)}/export",
            _ce_export_params(format, shape, page_type, kind),
        )
        return AsyncExportDownload(response, client)

    async def download_crawl_extract(
        self,
        job_id: str,
        path: str,
        format: str = "json",
        shape: Optional[str] = None,
        page_type: Optional[str] = None,
        kind: Optional[str] = None,
    ) -> SavedExport:
        """Async equivalent of WebgrphNamespace.download_crawl_extract."""
        return await asave_export(
            await self.export_crawl_extract(job_id, format, shape, page_type, kind),
            path,
        )

    async def cancel_crawl_extract(self, job_id: str) -> CrawlExtractCancelResult:
        """Async equivalent of WebgrphNamespace.cancel_crawl_extract."""
        return await arun(self._t, _ops_ce_cancel(job_id))

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

    async def list_sessions(self, active_only: bool = True) -> List[Dict[str, Any]]:
        return await arun(
            self._t,
            _Op(
                "GET",
                "webgrph/sessions",
                params={"active_only": "true" if active_only else "false"},
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
        return await arun(self._t, _Op("GET", f"webgrph/sessions/{seg(session_id)}"))

    async def delete_session(self, session_id: str) -> None:
        await arun(self._t, _Op("DELETE", f"webgrph/sessions/{seg(session_id)}"))

    async def end_session(self, session_id: str) -> Dict[str, Any]:
        return await arun(
            self._t, _Op("POST", f"webgrph/sessions/{seg(session_id)}/end", {})
        )

    async def update_session_job(self, session_id: str, job_id: str) -> Dict[str, Any]:
        return await arun(
            self._t,
            _Op(
                "PATCH", f"webgrph/sessions/{seg(session_id)}/job", params={"job_id": job_id}
            ),
        )
