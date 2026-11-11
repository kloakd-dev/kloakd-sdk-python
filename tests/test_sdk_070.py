"""The changes after 0.6.0, each against the shape kobe-scraper's code sends
or reads.

Backend references are paths under kobe-scraper src/kobe_scraper/ (main at
6bd19e9b, 12 November 2026).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import respx
from httpx import Response

import kloakd
from kloakd import (
    ApiError,
    AsyncKloakd,
    CrawlContinueResult,
    CrawlExtractCrawl,
    ExportCrawl,
    Kloakd,
    LoginSession,
    SessionStatus,
)
from kloakd.modules.webgrph import _node
from tests.conftest import ORG_PREFIX, TEST_BASE_URL, TEST_ORG_ID, mock_response

BASE = f"{TEST_BASE_URL}{ORG_PREFIX}"
CRAWL = f"{BASE}/webgrph/crawl"
CE = f"{BASE}/webgrph/crawl-extract"
JOB = "job-1"
BATCH = "batch-1"
HELD_MESSAGE = "Paused: the organization's quota ran out. It resumes by itself."


@pytest.fixture
def client() -> Kloakd:
    return Kloakd(
        api_key="sk-test-k", organization_id=TEST_ORG_ID, base_url=TEST_BASE_URL
    )


@pytest.fixture
def aclient() -> AsyncKloakd:
    return AsyncKloakd(
        api_key="sk-test-k", organization_id=TEST_ORG_ID, base_url=TEST_BASE_URL
    )


def _body(route: Any, i: int = -1) -> Any:
    return json.loads(route.calls[i].request.content)


def _started(crawl_id: str = "c1") -> Response:
    # modules/webgrph/router.py CrawlResponse (202)
    return mock_response(
        {"success": True, "crawl_id": crawl_id, "url": "https://s.test"},
        status_code=202,
    )


def _status(state: str, **over: Any) -> dict[str, Any]:
    # modules/webgrph/router.py CrawlStatusResponse
    return {
        "crawl_id": "c1", "status": state, "organization_id": TEST_ORG_ID,
        "total_pages": 0, "max_depth_reached": 0, "artifact_id": None,
        "error": None, "graph_data": None, **over,
    }


def _held() -> dict[str, Any]:
    # billing/held_work.py: a held crawl's status body carries the message
    return _status("held_quota", message=HELD_MESSAGE, total_pages=7)


PARTIAL = {
    "is_partial": True, "partial_reason": "time_budget", "resumable": True,
    "pages_discovered": 40, "pages_fetched": 25, "pages_unfetched": 15,
}
NODE = {
    "id": "1", "url": "https://s.test/a", "parent_url": "https://s.test/",
    "children_urls": [], "depth": 1, "category": "page",
    "classification_confidence": 0.0,
    "metadata": {"title": "A", "is_grouping": False, "fetch_status": "fetched"},
}


def _pages(nodes: list[dict[str, Any]]) -> Response:
    return mock_response(
        {"crawl_id": "c1", "nodes": nodes, "next_cursor": None, "total": len(nodes)}
    )


# ── 1. Extraction text is text/plain (modules/skanyr/router.py:1358-1378) ──


@respx.mock
@pytest.mark.parametrize("text", ["Hello world", "123", '{"a": 1}', "null", ""])
def test_extraction_text_is_returned_as_the_string_sent(
    client: Kloakd, text: str
) -> None:
    respx.get(f"{BASE}/skanyr/extractions/h1/text").mock(
        return_value=Response(
            200, text=text, headers={"content-type": "text/plain; charset=utf-8"}
        )
    )
    got = client.skanyr.get_extraction_text("h1")
    assert isinstance(got, str) and got == text


@respx.mock
def test_extraction_text_keeps_non_ascii_and_maps_errors(client: Kloakd) -> None:
    respx.get(f"{BASE}/skanyr/extractions/h1/text").mock(
        side_effect=[
            Response(200, content="Żółw – 東京".encode()),
            Response(404, json={"detail": "Extraction not found"}),
        ]
    )
    assert client.skanyr.get_extraction_text("h1") == "Żółw – 東京"
    with pytest.raises(ApiError) as caught:
        client.skanyr.get_extraction_text("h1")
    assert caught.value.status_code == 404


@respx.mock
async def test_async_extraction_text_is_a_string(aclient: AsyncKloakd) -> None:
    respx.get(f"{BASE}/skanyr/extractions/h%2F1/text").mock(
        side_effect=[
            Response(200, text='{"a": 1}', headers={"content-type": "text/plain"}),
            Response(404, json={"detail": "Extraction not found"}),
        ]
    )
    assert await aclient.skanyr.get_extraction_text("h/1") == '{"a": 1}'
    with pytest.raises(ApiError) as caught:
        await aclient.skanyr.get_extraction_text("h/1")
    assert caught.value.status_code == 404


# ── 2. A crawl held for quota is a pause (billing/held_work.py:1-45) ──


def _assert_held(crawl: kloakd.CrawlResult, url: str = "https://s.test") -> None:
    assert (crawl.status, crawl.held, crawl.message) == (
        "held_quota", True, HELD_MESSAGE,
    )
    assert (crawl.success, crawl.ok, crawl.error) == (False, False, None)
    assert (crawl.crawl_id, crawl.url, crawl.pages) == ("c1", url, [])
    assert crawl.total_pages == 7


@respx.mock
def test_crawl_returns_a_held_crawl_without_loading_pages(client: Kloakd) -> None:
    respx.post(CRAWL).mock(return_value=_started())
    status = respx.get(f"{CRAWL}/c1").mock(
        side_effect=[mock_response(_status("running")), mock_response(_held())]
    )
    pages = respx.get(f"{CRAWL}/c1/pages").mock(return_value=_pages([NODE]))
    _assert_held(client.webgrph.crawl("https://s.test", poll_interval=0.001))
    assert status.call_count == 2 and not pages.called


@respx.mock
def test_wait_for_crawl_returns_held_then_the_finished_crawl(client: Kloakd) -> None:
    status = respx.get(f"{CRAWL}/c1").mock(
        side_effect=[
            mock_response(_held()),
            mock_response(_status("running")),
            mock_response(_status("completed", total_pages=1, artifact_id="art-1")),
        ]
    )
    respx.get(f"{CRAWL}/c1/pages").mock(return_value=_pages([NODE]))
    _assert_held(client.webgrph.wait_for_crawl("c1", poll_interval=0.001), url="")
    assert status.call_count == 1

    done = client.webgrph.wait_for_crawl(
        "c1", poll_interval=0.001, url="https://s.test"
    )
    assert (done.success, done.status, done.held) == (True, "completed", False)
    assert (done.url, done.artifact_id) == ("https://s.test", "art-1")
    assert [p.url for p in done.pages] == ["https://s.test/a"]
    assert (done.is_partial, done.resumable, done.message) == (None, None, None)


@respx.mock
def test_crawl_all_gives_no_pages_for_a_held_crawl(client: Kloakd) -> None:
    respx.post(CRAWL).mock(return_value=_started())
    respx.get(f"{CRAWL}/c1").mock(return_value=mock_response(_held()))
    pages = respx.get(f"{CRAWL}/c1/pages").mock(return_value=_pages([NODE]))
    assert client.webgrph.crawl_all("https://s.test", poll_interval=0.001) == []
    assert not pages.called


@respx.mock
def test_wait_for_crawl_keeps_the_timeout_and_failure_results(client: Kloakd) -> None:
    respx.get(f"{CRAWL}/c1").mock(return_value=mock_response(_status("running")))
    late = client.webgrph.wait_for_crawl("c1", poll_timeout=0, poll_interval=0.001)
    assert (late.success, late.held, late.status) == (False, False, "running")
    assert late.error == "Crawl c1 still running after 0s"

    respx.get(f"{CRAWL}/c2").mock(
        return_value=mock_response(
            _status(
                "failed", crawl_id="c2", error="held too long",
                error_code="held_quota_expired",
            )
        )
    )
    failed = client.webgrph.wait_for_crawl("c2", poll_interval=0.001)
    assert (failed.success, failed.held) == (False, False)
    assert (failed.error, failed.error_code) == ("held too long", "held_quota_expired")

    respx.get(f"{CRAWL}/c3").mock(
        return_value=mock_response(_status("cancelled", crawl_id="c3"))
    )
    assert client.webgrph.wait_for_crawl("c3").error == "Crawl cancelled"


@respx.mock
async def test_async_crawl_and_wait_for_crawl_return_held(
    aclient: AsyncKloakd,
) -> None:
    respx.post(CRAWL).mock(return_value=_started())
    respx.get(f"{CRAWL}/c1").mock(return_value=mock_response(_held()))
    pages = respx.get(f"{CRAWL}/c1/pages").mock(return_value=_pages([NODE]))
    _assert_held(await aclient.webgrph.crawl("https://s.test", poll_interval=0.001))
    _assert_held(await aclient.webgrph.wait_for_crawl("c1"), url="")
    assert await aclient.webgrph.crawl_all("https://s.test") == []
    assert not pages.called


@respx.mock
async def test_async_wait_for_crawl_loads_pages_and_times_out(
    aclient: AsyncKloakd,
) -> None:
    respx.get(f"{CRAWL}/c1").mock(
        side_effect=[
            mock_response(_status("running")),
            mock_response(_status("completed", total_pages=1, **PARTIAL)),
        ]
    )
    respx.get(f"{CRAWL}/c1/pages").mock(return_value=_pages([NODE]))
    done = await aclient.webgrph.wait_for_crawl("c1", poll_interval=0.001)
    assert (done.success, done.is_partial, done.resumable) == (True, True, True)
    assert [p.title for p in done.pages] == ["A"]

    respx.get(f"{CRAWL}/c2").mock(
        return_value=mock_response(_status("queued", crawl_id="c2"))
    )
    late = await aclient.webgrph.wait_for_crawl(
        "c2", poll_timeout=0, poll_interval=0.001
    )
    assert (late.success, late.error) == (False, "Crawl c2 still running after 0s")


@respx.mock
def test_the_site_crawl_reports_a_held_crawl(client: Kloakd) -> None:
    respx.post(CRAWL).mock(return_value=_started())
    respx.get(f"{CRAWL}/c1").mock(return_value=mock_response(_held()))
    fetch = respx.post(f"{BASE}/evadr/fetch").mock(return_value=mock_response({}))
    site = client.crawl("https://s.test", poll_interval=0.001)
    assert (site.held, site.crawl_status, site.crawl_id) == (True, "held_quota", "c1")
    assert (site.success, site.error, site.message) == (False, None, HELD_MESSAGE)
    assert site.pages == [] and not fetch.called

    events = list(client.crawl_stream("https://s.test", poll_interval=0.001))
    found = [e for e in events if e.type == "discovery_complete"]
    assert len(found) == 1 and found[0].error is None
    assert found[0].metadata == {
        "pages_found": 7, "crawl_id": "c1", "status": "held_quota",
        "held": True, "message": HELD_MESSAGE,
    }
    assert not any(e.type.startswith("page_") for e in events)
    assert not fetch.called


@respx.mock
async def test_the_async_site_crawl_reports_a_held_crawl(
    aclient: AsyncKloakd,
) -> None:
    respx.post(CRAWL).mock(return_value=_started())
    respx.get(f"{CRAWL}/c1").mock(return_value=mock_response(_held()))
    site = await aclient.crawl("https://s.test", poll_interval=0.001)
    assert (site.held, site.crawl_status, site.crawl_id) == (True, "held_quota", "c1")
    assert (site.success, site.error, site.message) == (False, None, HELD_MESSAGE)

    events = [
        e async for e in aclient.crawl_stream("https://s.test", poll_interval=0.001)
    ]
    found = [e for e in events if e.type == "discovery_complete"]
    assert found[0].metadata["held"] is True
    assert found[0].metadata["status"] == "held_quota"


# ── 3. What a crawl did (modules/webgrph/router.py:80-99) ──


@respx.mock
def test_a_partial_crawl_is_completed_and_says_what_it_left(client: Kloakd) -> None:
    # tasks/crawl_tasks.py:767-779: a partial crawl ends "completed"
    respx.post(CRAWL).mock(return_value=_started())
    respx.get(f"{CRAWL}/c1").mock(
        return_value=mock_response(_status("completed", total_pages=25, **PARTIAL))
    )
    respx.get(f"{CRAWL}/c1/pages").mock(return_value=_pages([NODE]))
    crawl = client.webgrph.crawl("https://s.test", poll_interval=0.001)
    assert (crawl.success, crawl.status, crawl.held) == (True, "completed", False)
    assert (crawl.is_partial, crawl.partial_reason, crawl.resumable) == (
        True, "time_budget", True,
    )
    assert (
        crawl.pages_discovered, crawl.pages_fetched, crawl.pages_unfetched,
    ) == (40, 25, 15)
    assert (crawl.error, crawl.error_code, crawl.message) == (None, None, None)


@respx.mock
def test_a_whole_crawl_reads_false_and_absent_fields_read_none(
    client: Kloakd,
) -> None:
    respx.get(f"{CRAWL}/c1").mock(
        side_effect=[
            mock_response(
                _status("completed", is_partial=False, resumable=False,
                        pages_discovered=3, pages_fetched=3, pages_unfetched=0)
            ),
            mock_response(_status("completed")),
        ]
    )
    respx.get(f"{CRAWL}/c1/pages").mock(return_value=_pages([]))
    whole = client.webgrph.wait_for_crawl("c1")
    assert (whole.is_partial, whole.resumable, whole.pages_unfetched) == (
        False, False, 0,
    )
    bare = client.webgrph.wait_for_crawl("c1")
    assert (bare.is_partial, bare.partial_reason, bare.resumable) == (None,) * 3
    assert (
        bare.pages_discovered, bare.pages_fetched, bare.pages_unfetched,
    ) == (None,) * 3


# ── 4. Continue a partial crawl (modules/webgrph/router.py:709-777) ──


@respx.mock
def test_continue_crawl_posts_to_the_crawl_and_reads_the_answer(
    client: Kloakd,
) -> None:
    route = respx.post(f"{CRAWL}/c%2F1/continue").mock(
        return_value=mock_response(
            {"success": True, "crawl_id": "c/1", "status": "queued"}, status_code=202
        )
    )
    assert client.webgrph.continue_crawl("c/1") == CrawlContinueResult(
        success=True, crawl_id="c/1", status="queued"
    )
    assert route.call_count == 1 and _body(route) == {}


@respx.mock
def test_continue_crawl_raises_the_409_of_a_crawl_that_cannot_continue(
    client: Kloakd,
) -> None:
    # modules/webgrph/router.py:736-743: an unknown crawl is a 409 too
    respx.post(f"{CRAWL}/c1/continue").mock(
        return_value=Response(409, json={"detail": "Crawl cannot be continued"})
    )
    with pytest.raises(ApiError) as caught:
        client.webgrph.continue_crawl("c1")
    assert caught.value.status_code == 409
    assert "cannot be continued" in caught.value.message


@respx.mock
async def test_async_continue_then_wait(aclient: AsyncKloakd) -> None:
    route = respx.post(f"{CRAWL}/c1/continue").mock(
        side_effect=[
            mock_response(
                {"success": True, "crawl_id": "c1", "status": "queued"},
                status_code=202,
            ),
            Response(409, json={"detail": "Crawl is already being continued"}),
        ]
    )
    respx.get(f"{CRAWL}/c1").mock(
        side_effect=[
            mock_response(_status("queued")),
            mock_response(
                _status("completed", is_partial=False, resumable=False,
                        pages_unfetched=0)
            ),
        ]
    )
    respx.get(f"{CRAWL}/c1/pages").mock(return_value=_pages([NODE]))
    again = await aclient.webgrph.continue_crawl("c1")
    assert (again.success, again.crawl_id, again.status) == (True, "c1", "queued")
    assert _body(route) == {}
    done = await aclient.webgrph.wait_for_crawl("c1", poll_interval=0.001)
    assert (done.is_partial, done.pages_unfetched, len(done.pages)) == (False, 0, 1)
    with pytest.raises(ApiError) as caught:
        await aclient.webgrph.continue_crawl("c1")
    assert caught.value.status_code == 409


# ── 7. Crawl limits are sent only when set (modules/webgrph/router.py:43-70) ──


@respx.mock
def test_crawl_limits_are_left_out_unless_given(client: Kloakd) -> None:
    route = respx.post(CRAWL).mock(return_value=_started())
    respx.get(f"{CRAWL}/c1").mock(return_value=mock_response(_held()))
    assert client.webgrph.start_crawl("https://s.test") == "c1"
    client.webgrph.crawl("https://s.test", wait=False)
    client.webgrph.crawl("https://s.test", poll_interval=0.001)
    client.crawl("https://s.test", poll_interval=0.001)
    for call in range(4):
        assert {"max_depth", "max_pages"}.isdisjoint(_body(route, call))
        assert _body(route, call)["url"] == "https://s.test"

    client.webgrph.start_crawl("https://s.test", max_depth=2, max_pages=40)
    client.crawl("https://s.test", max_depth=0, max_pages=1, poll_interval=0.001)
    assert (_body(route, 4)["max_depth"], _body(route, 4)["max_pages"]) == (2, 40)
    assert (_body(route, 5)["max_depth"], _body(route, 5)["max_pages"]) == (0, 1)


@respx.mock
async def test_async_crawl_limits_are_left_out_unless_given(
    aclient: AsyncKloakd,
) -> None:
    route = respx.post(CRAWL).mock(return_value=_started())
    respx.get(f"{CRAWL}/c1").mock(return_value=mock_response(_held()))
    await aclient.webgrph.start_crawl("https://s.test")
    await aclient.webgrph.crawl("https://s.test", poll_interval=0.001)
    await aclient.crawl("https://s.test", poll_interval=0.001)
    for call in range(3):
        assert {"max_depth", "max_pages"}.isdisjoint(_body(route, call))
    await aclient.webgrph.crawl("https://s.test", max_depth=1, max_pages=5)
    assert (_body(route, 3)["max_depth"], _body(route, 3)["max_pages"]) == (1, 5)


@respx.mock
def test_the_crawl_stream_leaves_the_limits_out_unless_given(client: Kloakd) -> None:
    route = respx.post(CRAWL).mock(return_value=_started())
    respx.get(f"{CRAWL}/c1/events").mock(
        return_value=Response(
            200,
            text='data: {"type": "completed", "total_pages": 0}\n\n',
            headers={"content-type": "text/event-stream"},
        )
    )
    first = list(client.webgrph.crawl_stream("https://s.test"))
    list(client.webgrph.crawl_stream("https://s.test", max_depth=1, max_pages=9))
    assert [e.type for e in first] == ["completed"]
    assert {"max_depth", "max_pages"}.isdisjoint(_body(route, 0))
    assert (_body(route, 1)["max_depth"], _body(route, 1)["max_pages"]) == (1, 9)


@respx.mock
async def test_the_async_crawl_stream_leaves_the_limits_out_unless_given(
    aclient: AsyncKloakd,
) -> None:
    route = respx.post(CRAWL).mock(return_value=_started())
    respx.get(f"{CRAWL}/c1/events").mock(
        return_value=Response(
            200,
            text='data: {"type": "completed", "total_pages": 0}\n\n',
            headers={"content-type": "text/event-stream"},
        )
    )
    first = [e async for e in aclient.webgrph.crawl_stream("https://s.test")]
    assert [e.type for e in first] == ["completed"]
    assert {"max_depth", "max_pages"}.isdisjoint(_body(route, 0))


# ── 7. Page nodes (modules/webgrph/router.py:113-127) ──


def test_a_node_carries_the_fetch_outcome_and_no_status_code() -> None:
    node = _node(
        {
            **NODE,
            "metadata": {
                "title": "A", "fetch_status": "unfetched",
                "fetch_error": "time_budget",
            },
        }
    )
    assert (node.fetch_status, node.fetch_error) == ("unfetched", "time_budget")
    assert not hasattr(node, "status_code")
    assert not hasattr(node, "crawl_parent_url")
    bare = _node({"url": "https://s.test/b", "depth": 0})
    assert (bare.title, bare.fetch_status, bare.fetch_error) == (None, None, None)
    assert (bare.children, bare.is_grouping) == ([], False)


# ── 7. Kolektr and Nexus results ──


@respx.mock
def test_extraction_carries_level_and_login_options(client: Kloakd) -> None:
    # modules/kolektr/router.py:228-254 ExtractResponse
    options = [{"method": "cookies"}, {"method": "interactive"}]
    respx.post(f"{BASE}/kolektr/extract").mock(
        side_effect=[
            mock_response(
                {
                    "success": True, "url": "https://s.test", "method": "level1",
                    "records": [{"t": "A"}], "total_records": 1, "level": 1,
                    "level_reason": "the schema matched",
                }
            ),
            mock_response(
                {
                    "success": False, "url": "https://s.test", "method": "",
                    "records": [], "total_records": 0, "auth_required": True,
                    "discovery_id": "d1", "login_options": options,
                }
            ),
        ]
    )
    done = client.kolektr.page("https://s.test")
    assert (done.level, done.level_reason, done.login_options) == (
        1, "the schema matched", None,
    )
    assert not hasattr(done, "has_more") and not hasattr(done, "total")
    walled = client.kolektr.page("https://s.test")
    assert (walled.auth_required, walled.discovery_id) == (True, "d1")
    assert (walled.level, walled.login_options) == (None, options)


@respx.mock
async def test_async_extraction_carries_level_and_login_options(
    aclient: AsyncKloakd,
) -> None:
    respx.post(f"{BASE}/kolektr/extract").mock(
        return_value=mock_response(
            {
                "success": True, "url": "https://s.test", "method": "level2",
                "records": [], "total_records": 0, "level": 2,
                "level_reason": "no schema", "login_options": [{"method": "cookies"}],
            }
        )
    )
    done = await aclient.kolektr.page("https://s.test")
    assert (done.level, done.level_reason) == (2, "no schema")
    assert done.login_options == [{"method": "cookies"}]


@respx.mock
def test_nexus_results_have_no_error_field(client: Kloakd) -> None:
    # modules/nexus/router.py:111-132, 158-170: no ``error`` in any answer
    respx.post(f"{BASE}/nexus/analyze").mock(
        return_value=mock_response(
            {"perception_id": "p1", "page_type": "listing", "confidence": 0.5,
             "error": "ignored"}
        )
    )
    respx.post(f"{BASE}/nexus/synthesize").mock(
        return_value=mock_response({"strategy_id": "s1", "program": "x"})
    )
    respx.post(f"{BASE}/nexus/verify").mock(
        side_effect=[
            mock_response({"strategy_id": "s1", "verified": True}),
            mock_response({"strategy_id": "s1", "verified": False}),
        ]
    )
    analysis = client.nexus.analyze("https://s.test", "<html/>")
    synthesis = client.nexus.synthesize("https://s.test", "<html/>", "titles")
    safe = client.nexus.verify("s1")
    unsafe = client.nexus.verify("s1")
    for result in (analysis, synthesis, safe, unsafe):
        assert not hasattr(result, "error")
    assert (analysis.ok, synthesis.ok, safe.ok, unsafe.ok) == (
        True, True, True, False,
    )


@respx.mock
def test_nexus_reason_sends_a_fractional_timeout(client: Kloakd) -> None:
    # modules/nexus/router.py:135-140 ReasonRequest.timeout_secs: Optional[float]
    route = respx.post(f"{BASE}/nexus/reason").mock(return_value=mock_response({}))
    client.nexus.reason("page_type", timeout_secs=2.5)
    client.nexus.reason("page_type")
    assert _body(route, 0) == {
        "query_type": "page_type", "parameters": [], "timeout_secs": 2.5,
    }
    assert "timeout_secs" not in _body(route, 1)


@respx.mock
async def test_async_nexus_results_and_timeout(aclient: AsyncKloakd) -> None:
    respx.post(f"{BASE}/nexus/verify").mock(
        return_value=mock_response({"strategy_id": "s1", "verified": True})
    )
    route = respx.post(f"{BASE}/nexus/reason").mock(return_value=mock_response({}))
    checked = await aclient.nexus.verify("s1")
    assert checked.ok is True and not hasattr(checked, "error")
    await aclient.nexus.reason("page_type", timeout_secs=0.25)
    assert _body(route)["timeout_secs"] == 0.25


# ── 2. Crawl and extract: the crawl object and a held crawl ──
# modules/webgrph/crawl_extract.py:1092-1118, crawl_extract_router.py:174-200


def _job(state: str, crawl: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "job_id": JOB, "crawl_id": "c1", "url": "https://s.test", "status": state,
        "cancel_requested": False,
        "progress": {"pages_crawled": 4, "pages_total": None, "pages_extracted": 3,
                     "pages_failed": 0, "items": 9},
        "error": None, "error_code": None, "crawl": crawl,
    }


CE_CRAWL = {
    "status": "completed", "is_partial": True, "partial_reason": "time_budget",
    "pages_discovered": 40, "pages_fetched": 25, "pages_unfetched": 15,
    "cancelled": False, "root_unfetched": False, "error": None, "error_code": None,
}


@respx.mock
def test_the_job_status_carries_what_its_crawl_did(client: Kloakd) -> None:
    respx.get(f"{CE}/{JOB}").mock(
        side_effect=[
            mock_response(_job("completed", CE_CRAWL)),
            mock_response(_job("crawling")),
        ]
    )
    done = client.webgrph.get_crawl_extract(JOB)
    assert done.crawl == CrawlExtractCrawl(
        status="completed", is_partial=True, partial_reason="time_budget",
        pages_discovered=40, pages_fetched=25, pages_unfetched=15,
    )
    assert (done.held, done.finished) == (False, True)
    early = client.webgrph.get_crawl_extract(JOB)
    assert (early.crawl, early.held, early.finished) == (None, False, False)


@respx.mock
def test_the_job_waiter_returns_a_job_whose_crawl_is_held(client: Kloakd) -> None:
    held = _job("crawling", {"status": "held_quota", "is_partial": None})
    status = respx.get(f"{CE}/{JOB}").mock(
        side_effect=[mock_response(_job("crawling")), mock_response(held)]
    )
    waited = client.webgrph.wait_for_crawl_extract(
        JOB, poll_interval=0.001, poll_timeout=5
    )
    assert (waited.held, waited.finished, waited.ok) == (True, False, False)
    assert (waited.status, waited.error) == ("crawling", None)
    assert waited.crawl is not None and waited.crawl.status == "held_quota"
    assert status.call_count == 2

    respx.post(CE).mock(
        return_value=mock_response(
            {"success": True, "job_id": JOB, "crawl_id": "c1",
             "url": "https://s.test", "status": "queued"},
            status_code=202,
        )
    )
    status.side_effect = [mock_response(held)]
    started = client.webgrph.crawl_extract("https://s.test", poll_interval=0.001)
    assert (started.job_id, started.held, started.finished) == (JOB, True, False)


@respx.mock
async def test_the_async_job_waiter_returns_a_job_whose_crawl_is_held(
    aclient: AsyncKloakd,
) -> None:
    held = _job("crawling", {"status": "held_quota"})
    respx.get(f"{CE}/{JOB}").mock(return_value=mock_response(held))
    respx.post(CE).mock(
        return_value=mock_response(
            {"success": True, "job_id": JOB, "crawl_id": "c1",
             "url": "https://s.test", "status": "queued"},
            status_code=202,
        )
    )
    waited = await aclient.webgrph.wait_for_crawl_extract(JOB, poll_interval=0.001)
    assert (waited.held, waited.finished) == (True, False)
    started = await aclient.webgrph.crawl_extract(
        "https://s.test", poll_interval=0.001
    )
    assert started.held is True
    assert started.crawl == CrawlExtractCrawl(status="held_quota")


# ── 6. Export headers (crawl_extract_router.py:402-427, 540-547) ──


def _export(headers: dict[str, str]) -> Response:
    return Response(
        200,
        content=b'{"t":"A"}\n',
        headers={
            "Content-Type": "application/x-ndjson",
            "Content-Disposition": 'attachment; filename="rows.ndjson"',
            **headers,
        },
    )


CRAWL_HEADERS = {
    "X-Job-Status": "completed", "X-Crawl-Status": "completed",
    "X-Crawl-Partial": "true", "X-Crawl-Partial-Reason": "time_budget",
    "X-Crawl-Pages-Discovered": "40", "X-Crawl-Pages-Fetched": "25",
    "X-Crawl-Pages-Unfetched": "15", "X-Crawl-Cancelled": "false",
    "X-Crawl-Root-Unfetched": "false",
}
CRAWL_FROM_HEADERS = ExportCrawl(
    status="completed", is_partial=True, partial_reason="time_budget",
    pages_discovered=40, pages_fetched=25, pages_unfetched=15,
    cancelled=False, root_unfetched=False,
)


@respx.mock
def test_the_export_reads_the_crawl_from_its_headers(
    client: Kloakd, tmp_path: Path
) -> None:
    respx.get(f"{CE}/{JOB}/export").mock(
        side_effect=[
            _export(CRAWL_HEADERS),
            _export({"X-Job-Status": "extracting", "X-Crawl-Status": "running",
                     "X-Crawl-Cancelled": "false"}),
            _export({"X-Job-Status": "completed"}),
            _export(CRAWL_HEADERS),
        ]
    )
    with client.webgrph.export_crawl_extract(JOB, format="ndjson") as export:
        assert (export.job_status, export.crawl) == ("completed", CRAWL_FROM_HEADERS)
    with client.webgrph.export_crawl_extract(JOB, format="ndjson") as export:
        assert export.job_status == "extracting"
        assert export.crawl == ExportCrawl(status="running", cancelled=False)
        assert (export.crawl.is_partial, export.crawl.pages_fetched) == (None, None)
    with client.webgrph.export_crawl_extract(JOB, format="ndjson") as export:
        assert (export.job_status, export.crawl) == ("completed", None)
    saved = client.webgrph.download_crawl_extract(
        JOB, str(tmp_path / "rows.ndjson"), format="ndjson"
    )
    assert (saved.job_status, saved.crawl) == ("completed", CRAWL_FROM_HEADERS)


@respx.mock
def test_a_batch_export_has_no_job_status_and_no_crawl(
    client: Kloakd, tmp_path: Path
) -> None:
    # kernel/batch_export_router.py:163-197: no X-Job-Status, no X-Crawl-*
    respx.get(f"{BASE}/batch-jobs/{BATCH}/export").mock(return_value=_export({}))
    with client.export_batch_job(BATCH, format="ndjson") as export:
        assert (export.job_status, export.crawl) == (None, None)
    saved = client.download_batch_job(
        BATCH, str(tmp_path / "b.ndjson"), format="ndjson"
    )
    assert (saved.job_status, saved.crawl) == (None, None)


@respx.mock
async def test_the_async_export_reads_the_crawl_from_its_headers(
    aclient: AsyncKloakd, tmp_path: Path
) -> None:
    respx.get(f"{CE}/{JOB}/export").mock(return_value=_export(CRAWL_HEADERS))
    respx.get(f"{BASE}/batch-jobs/{BATCH}/export").mock(return_value=_export({}))
    async with await aclient.webgrph.export_crawl_extract(JOB) as export:
        assert (export.job_status, export.crawl) == ("completed", CRAWL_FROM_HEADERS)
    saved = await aclient.webgrph.download_crawl_extract(
        JOB, str(tmp_path / "rows.json")
    )
    assert saved.crawl == CRAWL_FROM_HEADERS
    async with await aclient.export_batch_job(BATCH) as batch:
        assert (batch.job_status, batch.crawl) == (None, None)
    kept = await aclient.download_batch_job(BATCH, str(tmp_path / "b.json"))
    assert (kept.job_status, kept.crawl) == (None, None)


# ── 5. Login sessions (modules/fetchyr/router.py:1799-1899, 2054-2119) ──


COOKIES = [{"name": "sid", "value": "v", "domain": "acme.example"}]
SESSION = {
    "artifact_id": "sess-1", "status": "paused", "target_domain": "acme.example",
    "auth_method": "cookies", "created_at": "2026-11-12T00:00:00Z",
    "expires_at": "2026-11-19T00:00:00Z", "last_used_at": "2026-11-12T01:00:00Z",
    "paused_at": "2026-11-12T01:00:01Z", "pause_reason": "challenge",
    "pause_message": "The site asked for a check.",
    "identity": {"user_agent": "UA", "country": "KE"}, "requests_this_hour": 12,
    "protections": {"rate": "40 requests an hour"},
}


@respx.mock
def test_a_login_session_from_cookies_is_ready(client: Kloakd) -> None:
    route = respx.post(f"{BASE}/fetchyr/login-sessions").mock(
        return_value=mock_response(
            {
                "method": "cookies", "status": "ready",
                "target_url": "https://acme.example/account",
                "session_artifact_id": "sess-1", "cookies_kept": 1,
                "cookies_dropped": ["_ga"], "protections": {"rate": "40 an hour"},
                "next": {"status": f"{ORG_PREFIX}/fetchyr/sessions/sess-1"},
                "message": "Session ready.",
            },
            status_code=201,
        )
    )
    login = client.fetchyr.start_login_session(
        "https://acme.example/account", method="cookies", cookies=COOKIES,
        user_agent="UA", country="KE",
    )
    assert _body(route) == {
        "target_url": "https://acme.example/account", "method": "cookies",
        "cookies": COOKIES, "user_agent": "UA", "country": "KE",
    }
    assert login == LoginSession(
        method="cookies", status="ready",
        target_url="https://acme.example/account", session_artifact_id="sess-1",
        next={"status": f"{ORG_PREFIX}/fetchyr/sessions/sess-1"}, cookies_kept=1,
        cookies_dropped=["_ga"], protections={"rate": "40 an hour"},
        message="Session ready.",
    )


@respx.mock
def test_an_interactive_login_session_waits_and_sends_only_what_was_set(
    client: Kloakd,
) -> None:
    route = respx.post(f"{BASE}/fetchyr/login-sessions").mock(
        side_effect=[
            mock_response(
                {
                    "method": "interactive", "status": "waiting_for_login",
                    "target_url": "https://acme.example/account",
                    "discovery_id": "d1", "next": {"status": "/auth-chain/d1"},
                    "message": "Log in.",
                },
                status_code=202,
            ),
            Response(422, json={"detail": "method 'cookies' needs cookies"}),
        ]
    )
    login = client.fetchyr.start_login_session("https://acme.example/account")
    assert _body(route) == {"target_url": "https://acme.example/account"}
    assert (login.method, login.status, login.discovery_id) == (
        "interactive", "waiting_for_login", "d1",
    )
    assert (login.session_artifact_id, login.cookies_kept) == (None, None)
    assert (login.cookies_dropped, login.protections) == ([], {})
    with pytest.raises(ApiError) as caught:
        client.fetchyr.start_login_session("https://acme.example", method="cookies")
    assert caught.value.status_code == 422
    assert _body(route) == {"target_url": "https://acme.example", "method": "cookies"}


@respx.mock
def test_get_and_resume_a_session(client: Kloakd) -> None:
    got = respx.get(f"{BASE}/fetchyr/sessions/sess%2F1").mock(
        return_value=mock_response({**SESSION, "artifact_id": "sess/1"})
    )
    resumed = respx.post(f"{BASE}/fetchyr/sessions/sess-1/resume").mock(
        side_effect=[
            mock_response({**SESSION, "status": "active", "paused_at": None,
                           "pause_reason": None, "pause_message": None}),
            Response(409, json={"detail": "Session is not paused"}),
        ]
    )
    status = client.fetchyr.get_session("sess/1")
    assert got.call_count == 1
    assert status == SessionStatus(**{**SESSION, "artifact_id": "sess/1"})
    assert (status.pause_reason, status.requests_this_hour) == ("challenge", 12)

    active = client.fetchyr.resume_session("sess-1")
    assert _body(resumed) == {}
    assert (active.status, active.paused_at, active.pause_reason) == (
        "active", None, None,
    )
    with pytest.raises(ApiError) as caught:
        client.fetchyr.resume_session("sess-1")
    assert caught.value.status_code == 409

    respx.get(f"{BASE}/fetchyr/sessions/gone").mock(
        return_value=Response(404, json={"detail": "Session not found"})
    )
    with pytest.raises(ApiError) as caught:
        client.fetchyr.get_session("gone")
    assert caught.value.status_code == 404


@respx.mock
async def test_async_login_sessions(aclient: AsyncKloakd) -> None:
    start = respx.post(f"{BASE}/fetchyr/login-sessions").mock(
        return_value=mock_response(
            {"method": "cookies", "status": "ready", "session_artifact_id": "sess-1",
             "target_url": "https://acme.example", "cookies_kept": 1},
            status_code=201,
        )
    )
    respx.get(f"{BASE}/fetchyr/sessions/sess-1").mock(
        return_value=mock_response(SESSION)
    )
    resume = respx.post(f"{BASE}/fetchyr/sessions/sess-1/resume").mock(
        side_effect=[
            mock_response({**SESSION, "status": "active"}),
            Response(409, json={"detail": "Session was signed out"}),
        ]
    )
    login = await aclient.fetchyr.start_login_session(
        "https://acme.example", method="cookies", cookies=COOKIES, user_agent="UA"
    )
    assert _body(start) == {
        "target_url": "https://acme.example", "method": "cookies",
        "cookies": COOKIES, "user_agent": "UA",
    }
    assert (login.status, login.session_artifact_id) == ("ready", "sess-1")
    assert await aclient.fetchyr.get_session("sess-1") == SessionStatus(**SESSION)
    assert (await aclient.fetchyr.resume_session("sess-1")).status == "active"
    assert _body(resume) == {}
    with pytest.raises(ApiError) as caught:
        await aclient.fetchyr.resume_session("sess-1")
    assert caught.value.status_code == 409


# ── The new names are public ──


def test_the_new_models_are_exported() -> None:
    names = {
        "CrawlContinueResult", "CrawlExtractCrawl", "ExportCrawl", "LoginSession",
        "SessionStatus",
    }
    assert names <= set(kloakd.__all__)
    for name in names:
        assert getattr(kloakd, name).__name__ == name
