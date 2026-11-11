"""After 0.6.0 (unreleased): the API on kobe-scraper integration/2026-11-12
(e5e358aa).

Crawl-extract (modules/webgrph/crawl_extract_router.py): start, status,
results (cursor), pages, export (streamed), cancel. Batch export
(kernel/batch_export_router.py). Every request is mocked with respx.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import respx
from httpx import Response

from kloakd import (
    ApiError,
    AsyncExportDownload,
    AsyncKloakd,
    CrawlExtractRow,
    ExportDownload,
    ForbiddenError,
    JobFailedError,
    JobTimeoutError,
    Kloakd,
)
from kloakd.modules.webgrph import CRAWL_EXTRACT_MAX_LIMIT
from tests.conftest import ORG_PREFIX, TEST_API_KEY, TEST_BASE_URL, TEST_ORG_ID
from tests.test_contract import _live

BASE = f"{TEST_BASE_URL}{ORG_PREFIX}"
CE = f"{BASE}/webgrph/crawl-extract"
JOB = "11111111-1111-1111-1111-111111111111"
BATCH = "22222222-2222-2222-2222-222222222222"
BOM = b"\xef\xbb\xbf"
CSV = BOM + b"page_url,title\r\nhttps://e.com/a,A\r\n"

LINKS = {
    "status": f"{ORG_PREFIX}/webgrph/crawl-extract/{JOB}",
    "results": f"{ORG_PREFIX}/webgrph/crawl-extract/{JOB}/results",
    "pages": f"{ORG_PREFIX}/webgrph/crawl-extract/{JOB}/pages",
    "cancel": f"{ORG_PREFIX}/webgrph/crawl-extract/{JOB}/cancel",
    "export": {
        f: f"{ORG_PREFIX}/webgrph/crawl-extract/{JOB}/export?format={f}"
        for f in ("json", "ndjson", "csv")
    },
    "crawl_events": f"{ORG_PREFIX}/webgrph/crawl/c-1/events",
    "events": f"{ORG_PREFIX}/webgrph/crawl-extract/{JOB}/events",
}


def started() -> dict[str, Any]:
    return {
        "success": True, "job_id": JOB, "crawl_id": "c-1", "url": "https://e.com",
        "status": "queued", "limits": {"max_pages": 50, "max_depth": 2}, "links": LINKS,
    }


def state(status: str, **over: Any) -> dict[str, Any]:
    return {
        "job_id": JOB, "crawl_id": "c-1", "url": "https://e.com", "status": status,
        "cancel_requested": False,
        "progress": {"pages_crawled": 4, "pages_total": 4, "pages_extracted": 3, "pages_failed": 1, "items": 12},
        "error": None, "error_code": None, "request": {"url": "https://e.com"},
        "created_at": "2026-11-12T00:00:00Z", "started_at": "2026-11-12T00:00:01Z",
        "completed_at": None, "updated_at": "2026-11-12T00:00:05Z", "links": LINKS,
        "pages_by_method": {"schema": 3},
        "shapes": [{"shape": "s1", "kind": "item", "rows": 12, "page_types": ["listing"], "fields": ["title"]}],
        **over,
    }


def row(i: int) -> dict[str, Any]:
    return {
        "page_url": f"https://e.com/{i}", "page_type": "listing", "row_kind": "item",
        "item_index": i, "data": {"title": f"t{i}"}, "shape": "s1",
    }


def _sent(route: respx.Route) -> dict[str, Any]:
    return json.loads(route.calls.last.request.content)


def _query(route: respx.Route, call: int = -1) -> dict[str, str]:
    return dict(route.calls[call].request.url.params)


@pytest.fixture
def aclient() -> AsyncKloakd:
    return AsyncKloakd(api_key=TEST_API_KEY, organization_id=TEST_ORG_ID, base_url=TEST_BASE_URL)


# ── The routes are the API's ────────────────────────────────────────────


def test_the_new_routes_are_in_the_route_list() -> None:
    job = f"{ORG_PREFIX}/webgrph/crawl-extract/{JOB}"
    assert _live("POST", f"{ORG_PREFIX}/webgrph/crawl-extract")
    assert all(_live("GET", job + tail) for tail in ("", "/results", "/pages", "/export"))
    assert _live("POST", f"{job}/cancel")
    assert _live("GET", f"{ORG_PREFIX}/batch-jobs/{BATCH}/export")


# ── Start, status, wait ─────────────────────────────────────────────────


@respx.mock
def test_start_sends_only_what_was_given_and_reads_the_job(client: Kloakd) -> None:
    route = respx.post(CE).mock(return_value=Response(202, json=started()))
    job = client.webgrph.start_crawl_extract("https://e.com")
    assert _sent(route) == {"url": "https://e.com"}
    assert (job.job_id, job.crawl_id, job.status, job.max_pages, job.max_depth) == (JOB, "c-1", "queued", 50, 2)
    assert job.links["export"]["csv"].endswith("/export?format=csv")


@respx.mock
def test_start_sends_the_crawl_options_and_the_extract_spec(client: Kloakd) -> None:
    route = respx.post(CE).mock(return_value=Response(202, json=started()))
    extract = {"schema": {"item_selector": "li.item", "fields": [{"name": "title", "selector": "h3"}]}}
    client.webgrph.start_crawl_extract(
        "https://e.com", max_depth=2, max_pages=50, include_external_links=False,
        session_artifact_id="sa-1", capture_mode="rendered", scope={"include": ["/shop"]},
        budget={"max_seconds": 60}, extract=extract,
    )
    assert _sent(route) == {
        "url": "https://e.com", "max_depth": 2, "max_pages": 50, "include_external_links": False,
        "session_artifact_id": "sa-1", "capture_mode": "rendered", "scope": {"include": ["/shop"]},
        "budget": {"max_seconds": 60}, "extract": extract,
    }


@respx.mock
def test_start_refused_for_a_plan_without_kolektr_raises_forbidden(client: Kloakd) -> None:
    respx.post(CE).mock(return_value=Response(403, json={"detail": {"error": "module_not_entitled", "message": "Kolektr is not in your plan"}}))
    with pytest.raises(ForbiddenError) as caught:
        client.webgrph.start_crawl_extract("https://e.com")
    assert caught.value.code == "module_not_entitled"


@respx.mock
def test_status_reads_progress_and_shapes(client: Kloakd) -> None:
    respx.get(f"{CE}/{JOB}").mock(return_value=Response(200, json=state("extracting")))
    s = client.webgrph.get_crawl_extract(JOB)
    assert (s.status, s.finished, s.ok) == ("extracting", False, False)
    assert (s.pages_crawled, s.pages_total, s.pages_extracted, s.pages_failed, s.items) == (4, 4, 3, 1, 12)
    assert s.pages_by_method == {"schema": 3}
    assert s.shapes[0]["fields"] == ["title"]
    assert s.links["results"].endswith("/results")


@respx.mock
def test_status_of_an_unknown_job_is_a_404(client: Kloakd) -> None:
    respx.get(f"{CE}/{JOB}").mock(return_value=Response(404, json={"detail": "Crawl-extract job not found"}))
    with pytest.raises(ApiError) as caught:
        client.webgrph.get_crawl_extract(JOB)
    assert caught.value.status_code == 404


@respx.mock
def test_wait_polls_until_the_job_ends(client: Kloakd) -> None:
    route = respx.get(f"{CE}/{JOB}").mock(side_effect=[
        Response(200, json=state("crawling")),
        Response(200, json=state("extracting")),
        Response(200, json=state("completed")),
    ])
    s = client.webgrph.wait_for_crawl_extract(JOB, poll_interval=0.001)
    assert (s.status, s.ok, route.call_count) == ("completed", True, 3)


@respx.mock
def test_wait_raises_job_timeout_while_the_job_still_runs(client: Kloakd) -> None:
    respx.get(f"{CE}/{JOB}").mock(return_value=Response(200, json=state("crawling")))
    with pytest.raises(JobTimeoutError) as caught:
        client.webgrph.wait_for_crawl_extract(JOB, poll_interval=0.001, poll_timeout=0.01)
    assert caught.value.job_id == JOB


@respx.mock
def test_crawl_extract_starts_and_waits(client: Kloakd) -> None:
    respx.post(CE).mock(return_value=Response(202, json=started()))
    respx.get(f"{CE}/{JOB}").mock(side_effect=[
        Response(200, json=state("crawling")), Response(200, json=state("completed")),
    ])
    s = client.webgrph.crawl_extract("https://e.com", max_pages=50, poll_interval=0.001)
    assert (s.job_id, s.ok) == (JOB, True)


@respx.mock
def test_crawl_extract_raises_job_failed_with_the_job_error(client: Kloakd) -> None:
    respx.post(CE).mock(return_value=Response(202, json=started()))
    respx.get(f"{CE}/{JOB}").mock(return_value=Response(200, json=state("failed", error="crawl failed: boom", error_code="crawl_failed")))
    with pytest.raises(JobFailedError) as caught:
        client.webgrph.crawl_extract("https://e.com", poll_interval=0.001)
    assert (caught.value.job_id, caught.value.message) == (JOB, "crawl failed: boom")


@respx.mock
def test_a_cancelled_job_is_returned_not_raised(client: Kloakd) -> None:
    respx.post(CE).mock(return_value=Response(202, json=started()))
    respx.get(f"{CE}/{JOB}").mock(return_value=Response(200, json=state("cancelled")))
    s = client.webgrph.crawl_extract("https://e.com", poll_interval=0.001)
    assert (s.status, s.finished, s.ok) == ("cancelled", True, False)


# ── Results and pages ───────────────────────────────────────────────────


@respx.mock
def test_results_send_the_filters_and_read_rows(client: Kloakd) -> None:
    route = respx.get(f"{CE}/{JOB}/results").mock(return_value=Response(200, json={
        "job_id": JOB, "status": "completed", "total": 3, "count": 2, "rows": [row(0), row(1)], "next_cursor": "1:2",
    }))
    page = client.webgrph.get_crawl_extract_results(JOB, limit=2, shape="s1", page_type="listing", kind="item")
    assert _query(route) == {"limit": "2", "shape": "s1", "page_type": "listing", "kind": "item"}
    assert (page.total, page.count, page.next_cursor) == (3, 2, "1:2")
    assert page.rows[1] == CrawlExtractRow(
        page_url="https://e.com/1", row_kind="item", item_index=1, data={"title": "t1"}, page_type="listing", shape="s1",
    )


@respx.mock
def test_results_without_arguments_send_no_query(client: Kloakd) -> None:
    route = respx.get(f"{CE}/{JOB}/results").mock(return_value=Response(200, json={"job_id": JOB, "status": "crawling", "total": 0, "count": 0, "rows": [], "next_cursor": None}))
    page = client.webgrph.get_crawl_extract_results(JOB)
    assert _query(route) == {}
    assert (page.rows, page.next_cursor) == ([], None)


@respx.mock
@pytest.mark.parametrize("limit", [0, CRAWL_EXTRACT_MAX_LIMIT + 1, True, 1.5])
def test_a_limit_outside_1_to_1000_is_refused_before_any_request(client: Kloakd, limit: Any) -> None:
    route = respx.get(url__regex=r".*").mock(return_value=Response(200, json={}))
    with pytest.raises(ValueError):
        client.webgrph.get_crawl_extract_results(JOB, limit=limit)
    with pytest.raises(ValueError):
        client.webgrph.get_crawl_extract_pages(JOB, limit=limit)
    assert not route.called


@respx.mock
def test_iterating_follows_the_cursor_to_the_last_page(client: Kloakd) -> None:
    route = respx.get(f"{CE}/{JOB}/results").mock(side_effect=[
        Response(200, json={"job_id": JOB, "status": "completed", "total": 3, "count": 2, "rows": [row(0), row(1)], "next_cursor": "1:2"}),
        Response(200, json={"job_id": JOB, "status": "completed", "total": 3, "count": 1, "rows": [row(2)], "next_cursor": None}),
    ])
    rows = list(client.webgrph.iter_crawl_extract_results(JOB, limit=2, kind="item"))
    assert [r.item_index for r in rows] == [0, 1, 2]
    assert _query(route, 0) == {"limit": "2", "kind": "item"}
    assert _query(route, 1) == {"limit": "2", "cursor": "1:2", "kind": "item"}
    assert route.call_count == 2


@respx.mock
def test_all_results_collects_every_page(client: Kloakd) -> None:
    respx.get(f"{CE}/{JOB}/results").mock(side_effect=[
        Response(200, json={"rows": [row(0)], "next_cursor": "0:1"}),
        Response(200, json={"rows": [row(1)], "next_cursor": None}),
    ])
    assert [r.data["title"] for r in client.webgrph.crawl_extract_all_results(JOB)] == ["t0", "t1"]


@respx.mock
def test_pages_send_offset_and_status_and_read_pages(client: Kloakd) -> None:
    route = respx.get(f"{CE}/{JOB}/pages").mock(return_value=Response(200, json={
        "job_id": JOB, "status": "completed", "count": 1, "offset": 10,
        "pages": [{"page_seq": 11, "page_url": "https://e.com/x", "page_type": "detail", "title": "X", "status": "failed",
                   "method": "schema", "item_count": 0, "detail": {"error": "timeout"}, "extracted_at": "2026-11-12T00:00:09Z"}],
    }))
    result = client.webgrph.get_crawl_extract_pages(JOB, limit=50, offset=10, status="failed")
    assert _query(route) == {"limit": "50", "offset": "10", "status": "failed"}
    assert (result.count, result.offset) == (1, 10)
    p = result.pages[0]
    assert (p.page_seq, p.page_url, p.status, p.method, p.detail) == (11, "https://e.com/x", "failed", "schema", {"error": "timeout"})


# ── Export and download ─────────────────────────────────────────────────


def _csv_response(name: str, status: str = "completed") -> Response:
    return Response(200, content=CSV, headers={
        "Content-Type": "text/csv; charset=utf-8",
        "Content-Disposition": f'attachment; filename="{name}"',
        "X-Job-Status": status,
    })


@respx.mock
def test_export_streams_the_file_and_reads_its_headers(client: Kloakd) -> None:
    route = respx.get(f"{CE}/{JOB}/export").mock(return_value=_csv_response(f"crawl-extract-{JOB}.csv", "extracting"))
    with client.webgrph.export_crawl_extract(JOB, format="csv", shape="s1", kind="item") as export:
        assert isinstance(export, ExportDownload)
        assert (export.filename, export.job_status) == (f"crawl-extract-{JOB}.csv", "extracting")
        assert export.content_type == "text/csv; charset=utf-8"
        body = b"".join(export.iter_bytes())
    assert body == CSV and body.startswith(BOM)
    assert _query(route) == {"format": "csv", "shape": "s1", "kind": "item"}


@respx.mock
def test_export_defaults_to_json_and_has_no_read_timeout(client: Kloakd) -> None:
    route = respx.get(f"{CE}/{JOB}/export").mock(return_value=Response(200, json=[{"a": 1}]))
    export = client.webgrph.export_crawl_extract(JOB)
    assert json.loads(export.read()) == [{"a": 1}]
    export.close()
    assert _query(route) == {"format": "json"}
    timeout = route.calls.last.request.extensions["timeout"]
    assert timeout["read"] is None and timeout["connect"] == 100.0


@respx.mock
def test_an_unknown_format_is_refused_before_any_request(client: Kloakd, tmp_path: Path) -> None:
    route = respx.get(url__regex=r".*").mock(return_value=Response(200, json={}))
    with pytest.raises(ValueError):
        client.webgrph.export_crawl_extract(JOB, format="xlsx")
    with pytest.raises(ValueError):
        client.webgrph.download_crawl_extract(JOB, str(tmp_path / "x"), format="xml")
    with pytest.raises(ValueError):
        client.export_batch_job(BATCH, format="parquet")
    assert not route.called and list(tmp_path.iterdir()) == []


@respx.mock
def test_download_writes_the_file_as_sent(client: Kloakd, tmp_path: Path) -> None:
    respx.get(f"{CE}/{JOB}/export").mock(return_value=_csv_response(f"crawl-extract-{JOB}.csv"))
    target = tmp_path / "rows.csv"
    saved = client.webgrph.download_crawl_extract(JOB, str(target), format="csv")
    assert target.read_bytes() == CSV
    assert (saved.path, saved.bytes, saved.filename, saved.job_status) == (str(target), len(CSV), f"crawl-extract-{JOB}.csv", "completed")


@respx.mock
def test_a_refused_download_raises_and_leaves_no_file(client: Kloakd, tmp_path: Path) -> None:
    respx.get(f"{CE}/{JOB}/export").mock(return_value=Response(404, json={"detail": "Crawl-extract job not found"}))
    target = tmp_path / "rows.json"
    with pytest.raises(ApiError) as caught:
        client.webgrph.download_crawl_extract(JOB, str(target))
    assert caught.value.status_code == 404
    assert "Crawl-extract job not found" in caught.value.message
    assert not target.exists()


@respx.mock
def test_an_export_answered_503_is_sent_again(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("kloakd._http.time.sleep", lambda _s: None)
    client = Kloakd(api_key=TEST_API_KEY, organization_id=TEST_ORG_ID, base_url=TEST_BASE_URL)
    route = respx.get(f"{CE}/{JOB}/export").mock(side_effect=[
        Response(503, json={"detail": "unavailable"}), Response(200, content=b'{"a":1}\n'),
    ])
    saved = client.webgrph.download_crawl_extract(JOB, str(tmp_path / "rows.ndjson"), format="ndjson")
    assert (route.call_count, saved.bytes) == (2, 8)


# ── Cancel ──────────────────────────────────────────────────────────────


@respx.mock
def test_cancel_reads_the_status(client: Kloakd) -> None:
    route = respx.post(f"{CE}/{JOB}/cancel").mock(return_value=Response(200, json={"success": True, "job_id": JOB, "crawl_id": "c-1", "status": "cancelling"}))
    r = client.webgrph.cancel_crawl_extract(JOB)
    assert (r.success, r.job_id, r.crawl_id, r.status) == (True, JOB, "c-1", "cancelling")
    assert route.called


@respx.mock
def test_cancelling_an_ended_job_is_a_409(client: Kloakd) -> None:
    respx.post(f"{CE}/{JOB}/cancel").mock(return_value=Response(409, json={"detail": "Job already completed"}))
    with pytest.raises(ApiError) as caught:
        client.webgrph.cancel_crawl_extract(JOB)
    assert caught.value.status_code == 409
    assert "Job already completed" in caught.value.message


# ── Batch export ────────────────────────────────────────────────────────


@respx.mock
def test_batch_export_streams_the_file(client: Kloakd) -> None:
    route = respx.get(f"{BASE}/batch-jobs/{BATCH}/export").mock(return_value=Response(
        200, content=b'{"url":"https://e.com"}\n',
        headers={"Content-Type": "application/x-ndjson", "Content-Disposition": f'attachment; filename="batch-{BATCH}.ndjson"'},
    ))
    with client.export_batch_job(BATCH, format="ndjson") as export:
        assert (export.filename, export.job_status) == (f"batch-{BATCH}.ndjson", None)
        assert export.read() == b'{"url":"https://e.com"}\n'
    assert _query(route) == {"format": "ndjson"}


@respx.mock
def test_batch_download_writes_the_file_and_a_404_leaves_none(client: Kloakd, tmp_path: Path) -> None:
    respx.get(f"{BASE}/batch-jobs/{BATCH}/export").mock(side_effect=[
        _csv_response(f"batch-{BATCH}.csv"), Response(404, json={"detail": "Batch job not found"}),
    ])
    saved = client.download_batch_job(BATCH, str(tmp_path / "batch.csv"), format="csv")
    assert (tmp_path / "batch.csv").read_bytes() == CSV and saved.bytes == len(CSV)
    with pytest.raises(ApiError) as caught:
        client.download_batch_job(BATCH, str(tmp_path / "missing.csv"), format="csv")
    assert caught.value.status_code == 404
    assert not (tmp_path / "missing.csv").exists()


# ── The async client does the same ──────────────────────────────────────


@respx.mock
async def test_async_start_wait_and_failure(aclient: AsyncKloakd) -> None:
    start = respx.post(CE).mock(return_value=Response(202, json=started()))
    respx.get(f"{CE}/{JOB}").mock(side_effect=[
        Response(200, json=state("crawling")), Response(200, json=state("completed")),
        Response(200, json=state("failed", error="boom")),
    ])
    s = await aclient.webgrph.crawl_extract("https://e.com", extract={"fields": ["title"]}, poll_interval=0.001)
    assert (s.job_id, s.ok) == (JOB, True)
    assert _sent(start) == {"url": "https://e.com", "extract": {"fields": ["title"]}}
    with pytest.raises(JobFailedError):
        await aclient.webgrph.crawl_extract("https://e.com", poll_interval=0.001)


@respx.mock
async def test_async_wait_times_out(aclient: AsyncKloakd) -> None:
    respx.get(f"{CE}/{JOB}").mock(return_value=Response(200, json=state("queued")))
    with pytest.raises(JobTimeoutError) as caught:
        await aclient.webgrph.wait_for_crawl_extract(JOB, poll_interval=0.001, poll_timeout=0.01)
    assert caught.value.job_id == JOB


@respx.mock
async def test_async_results_pages_and_cancel(aclient: AsyncKloakd) -> None:
    results = respx.get(f"{CE}/{JOB}/results").mock(side_effect=[
        Response(200, json={"rows": [row(0), row(1)], "next_cursor": "1:2"}),
        Response(200, json={"rows": [row(2)], "next_cursor": None}),
        Response(200, json={"rows": [row(0)], "next_cursor": None}),
    ])
    rows = [r async for r in aclient.webgrph.iter_crawl_extract_results(JOB, limit=2)]
    assert [r.item_index for r in rows] == [0, 1, 2]
    assert _query(results, 1) == {"limit": "2", "cursor": "1:2"}
    assert len(await aclient.webgrph.crawl_extract_all_results(JOB)) == 1
    with pytest.raises(ValueError):
        await aclient.webgrph.get_crawl_extract_results(JOB, limit=1001)

    respx.get(f"{CE}/{JOB}/pages").mock(return_value=Response(200, json={"job_id": JOB, "status": "completed", "count": 0, "offset": 0, "pages": []}))
    assert (await aclient.webgrph.get_crawl_extract_pages(JOB, status="extracted")).pages == []

    respx.post(f"{CE}/{JOB}/cancel").mock(return_value=Response(200, json={"success": True, "job_id": JOB, "crawl_id": "c-1", "status": "cancelled"}))
    assert (await aclient.webgrph.cancel_crawl_extract(JOB)).status == "cancelled"


@respx.mock
async def test_async_export_and_download(aclient: AsyncKloakd, tmp_path: Path) -> None:
    route = respx.get(f"{CE}/{JOB}/export").mock(side_effect=[
        _csv_response(f"crawl-extract-{JOB}.csv"), _csv_response(f"crawl-extract-{JOB}.csv"),
        Response(404, json={"detail": "Crawl-extract job not found"}),
    ])
    async with await aclient.webgrph.export_crawl_extract(JOB, format="csv") as export:
        assert isinstance(export, AsyncExportDownload)
        assert export.filename == f"crawl-extract-{JOB}.csv"
        assert b"".join([c async for c in export.aiter_bytes()]) == CSV
    assert route.calls.last.request.extensions["timeout"]["read"] is None

    saved = await aclient.webgrph.download_crawl_extract(JOB, str(tmp_path / "rows.csv"), format="csv")
    assert (tmp_path / "rows.csv").read_bytes() == CSV and saved.bytes == len(CSV)

    with pytest.raises(ApiError):
        await aclient.webgrph.download_crawl_extract(JOB, str(tmp_path / "none.csv"), format="csv")
    assert not (tmp_path / "none.csv").exists()
    with pytest.raises(ValueError):
        await aclient.webgrph.export_crawl_extract(JOB, format="xlsx")


@respx.mock
async def test_async_batch_export_and_download(aclient: AsyncKloakd, tmp_path: Path) -> None:
    route = respx.get(f"{BASE}/batch-jobs/{BATCH}/export").mock(return_value=Response(
        200, content=b"[]", headers={"Content-Disposition": f'attachment; filename="batch-{BATCH}.json"'},
    ))
    export = await aclient.export_batch_job(BATCH)
    assert (await export.aread(), export.filename) == (b"[]", f"batch-{BATCH}.json")
    await export.aclose()
    assert _query(route) == {"format": "json"}
    saved = await aclient.download_batch_job(BATCH, str(tmp_path / "b.json"))
    assert (tmp_path / "b.json").read_bytes() == b"[]" and saved.bytes == 2
