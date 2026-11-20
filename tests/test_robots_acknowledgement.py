"""robots.txt: the acknowledgement field and the stop's typed errors.

The contract is kobe-scraper core/compliance/robots.py: a route that stops
answers 409 ``ROBOTS_DISALLOWED`` (``stop_detail``); the caller goes past it
by naming the host in ``robots_acknowledged_hosts`` in the same request
(``RobotsAcknowledgementField``; a query parameter on kolektr extract-all).
KLOAKD failing to ask answers 503 ``ROBOTS_CHECK_UNAVAILABLE``
(``unavailable``), with ``reason`` ``exits_refused`` when every exit refused
the site.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List

import pytest
import respx
from httpx import Response

from kloakd import (
    ApiError,
    AsyncKloakd,
    ConcurrencyLimitError,
    Kloakd,
    KloakdError,
    RobotsCheckUnavailableError,
    RobotsDisallowedError,
    RobotsExitsRefusedError,
)
from tests.conftest import ORG_PREFIX, TEST_BASE_URL, TEST_ORG_ID, mock_response

BASE = f"{TEST_BASE_URL}{ORG_PREFIX}"
HOSTS = ["www.reddit.com"]
ACK = "robots_acknowledged_hosts"

STOP = {
    "error": "ROBOTS_DISALLOWED",
    "code": "ROBOTS_DISALLOWED",
    "reason": "disallowed",
    "host": "www.reddit.com",
    "url": "https://www.reddit.com/r/Python/",
    "rule": "Disallow: /",
    "message": "www.reddit.com does not allow this in its robots.txt.",
    "acknowledge_field": "robots_acknowledged_hosts",
    "terms_version": "draft-2026-11-19",
}


@pytest.fixture
def aclient() -> AsyncKloakd:
    return AsyncKloakd(
        api_key="sk-test-key", organization_id=TEST_ORG_ID, base_url=TEST_BASE_URL
    )


def _body(route: Any, call: int = -1) -> Dict[str, Any]:
    request = route.calls[call].request
    return json.loads(request.content) if request.content else {}


_FETCH = {"success": True, "url": "https://e.com", "status_code": 200, "html": ""}
_CRAWL_STARTED = {"crawl_id": "c1"}
_CE_STARTED = {"success": True, "job_id": "j1", "crawl_id": "c1", "status": "queued"}
_ESTIMATE = {"max_depth": 1, "max_pages": 5}
_UNIFIED = {"success": True, "job_id": "u1", "status": "completed"}
_BATCH = {"id": "b1", "status": "pending"}

# (namespace path, method, args, extra kwargs, HTTP path, response)
_BODY_ROUTES: List[Any] = [
    ("evadr", "fetch", ("https://e.com",), {}, "evadr/fetch", _FETCH),
    ("evadr", "fetch_async", ("https://e.com",), {}, "evadr/fetch/async", {"job_id": "f1"}),
    ("evadr", "scan", ("https://e.com",), {}, "evadr/scan", {}),
    ("evadr", "profile", ("https://e.com",), {}, "evadr/profile", {}),
    ("kolektr", "page", ("https://e.com",), {}, "kolektr/extract", {"success": True}),
    ("kolektr", "page_all", ("https://e.com",), {}, "kolektr/extract", {"success": True}),
    ("webgrph", "start_crawl", ("https://e.com",), {}, "webgrph/crawl", _CRAWL_STARTED),
    ("webgrph", "estimate_crawl", ("https://e.com",), {}, "webgrph/crawl/estimate", _ESTIMATE),
    ("webgrph", "continue_crawl", ("c1",), {}, "webgrph/crawl/c1/continue", {"crawl_id": "c1"}),
    ("webgrph", "map_site", ("https://e.com",), {}, "webgrph/map", {"url": "https://e.com"}),
    ("webgrph", "reader_view", ("https://e.com",), {}, "webgrph/reader-view", {}),
    ("webgrph", "start_crawl_extract", ("https://e.com",), {}, "webgrph/crawl-extract", _CE_STARTED),
    ("webgrph", "estimate_crawl_extract", ("https://e.com",), {}, "webgrph/crawl-extract/estimate", _ESTIMATE),
    ("webgrph", "continue_crawl_extract", ("j1",), {}, "webgrph/crawl-extract/j1/continue", {"job_id": "j1"}),
    ("skanyr", "sync", ("site-1",), {}, "skanyr/sync", {}),
    ("", "unified_scrape", ("https://e.com",), {}, "scraping/unified", _UNIFIED),
    ("", "create_batch_job", (["https://e.com"],), {}, "batch-jobs", _BATCH),
]


def _target(obj: Any, namespace: str, method: str) -> Callable[..., Any]:
    return getattr(getattr(obj, namespace) if namespace else obj, method)


@pytest.mark.parametrize(("ns", "method", "args", "kw", "path", "answer"), _BODY_ROUTES)
@respx.mock
def test_each_method_sends_the_hosts_only_when_given(
    client: Kloakd, ns: str, method: str, args: Any, kw: Any, path: str, answer: Any
) -> None:
    route = respx.post(f"{BASE}/{path}").mock(return_value=mock_response(answer))
    _target(client, ns, method)(*args, **kw)
    _target(client, ns, method)(*args, robots_acknowledged_hosts=HOSTS, **kw)
    _target(client, ns, method)(*args, robots_acknowledged_hosts=[], **kw)
    assert ACK not in _body(route, 0)
    assert _body(route, 1)[ACK] == HOSTS
    assert ACK not in _body(route, 2)


@pytest.mark.parametrize(("ns", "method", "args", "kw", "path", "answer"), _BODY_ROUTES)
@respx.mock
async def test_each_async_method_sends_the_hosts_only_when_given(
    aclient: AsyncKloakd, ns: str, method: str, args: Any, kw: Any, path: str, answer: Any
) -> None:
    route = respx.post(f"{BASE}/{path}").mock(return_value=mock_response(answer))
    await _target(aclient, ns, method)(*args, **kw)
    await _target(aclient, ns, method)(*args, robots_acknowledged_hosts=HOSTS, **kw)
    assert ACK not in _body(route, 0)
    assert _body(route, 1)[ACK] == HOSTS


@respx.mock
def test_a_continue_with_only_the_hosts_sends_a_body(client: Kloakd) -> None:
    route = respx.post(f"{BASE}/webgrph/crawl/c1/continue").mock(
        return_value=mock_response({"crawl_id": "c1"})
    )
    client.webgrph.continue_crawl("c1")
    client.webgrph.continue_crawl("c1", robots_acknowledged_hosts=HOSTS)
    assert route.calls[0].request.content == b""
    assert _body(route, 1) == {ACK: HOSTS}


@respx.mock
def test_extract_all_sends_the_hosts_as_a_repeated_query_parameter(
    client: Kloakd,
) -> None:
    route = respx.post(url__regex=rf"{BASE}/kolektr/api-data/.+/extract-all.*").mock(
        return_value=mock_response({"job_id": "x"})
    )
    client.kolektr.extract_all_api_data("https://api.e.com/v1")
    client.kolektr.extract_all_api_data(
        "https://api.e.com/v1", robots_acknowledged_hosts=["api.e.com", "e.com:8443"]
    )
    assert ACK not in route.calls[0].request.url.params
    assert route.calls[1].request.url.params.get_list(ACK) == ["api.e.com", "e.com:8443"]


@respx.mock
async def test_async_extract_all_sends_the_hosts_as_a_query_parameter(
    aclient: AsyncKloakd,
) -> None:
    route = respx.post(url__regex=rf"{BASE}/kolektr/api-data/.+/extract-all.*").mock(
        return_value=mock_response({"job_id": "x"})
    )
    await aclient.kolektr.extract_all_api_data("https://api.e.com/v1", robots_acknowledged_hosts=HOSTS)
    assert route.calls[0].request.url.params.get_list(ACK) == HOSTS


@respx.mock
def test_the_crawl_and_its_stream_send_the_hosts(client: Kloakd) -> None:
    route = respx.post(f"{BASE}/webgrph/crawl").mock(return_value=mock_response(_CRAWL_STARTED))
    respx.get(f"{BASE}/webgrph/crawl/c1").mock(
        return_value=mock_response({"crawl_id": "c1", "status": "completed", "total_pages": 0})
    )
    respx.get(f"{BASE}/webgrph/crawl/c1/pages").mock(return_value=mock_response({"nodes": []}))
    respx.get(f"{BASE}/webgrph/crawl/c1/events").mock(
        return_value=Response(
            200,
            text='data: {"type": "completed", "total_pages": 0}\n\n',
            headers={"content-type": "text/event-stream"},
        )
    )
    client.webgrph.crawl("https://e.com", robots_acknowledged_hosts=HOSTS)
    list(client.webgrph.crawl_stream("https://e.com", robots_acknowledged_hosts=HOSTS))
    client.webgrph.crawl_all("https://e.com", robots_acknowledged_hosts=HOSTS)
    assert [_body(route, i)[ACK] for i in range(3)] == [HOSTS] * 3


@respx.mock
def test_the_site_crawl_sends_the_hosts_with_the_crawl_and_each_page(
    client: Kloakd,
) -> None:
    crawl = respx.post(f"{BASE}/webgrph/crawl").mock(return_value=mock_response(_CRAWL_STARTED))
    respx.get(f"{BASE}/webgrph/crawl/c1").mock(
        return_value=mock_response({"crawl_id": "c1", "status": "completed", "total_pages": 1})
    )
    respx.get(f"{BASE}/webgrph/crawl/c1/pages").mock(
        return_value=mock_response({"nodes": [{"url": "https://e.com/a", "depth": 0}]})
    )
    fetch = respx.post(f"{BASE}/evadr/fetch").mock(return_value=mock_response(_FETCH))
    extract = respx.post(f"{BASE}/kolektr/extract").mock(
        return_value=mock_response({"success": True, "records": [{"t": "x"}]})
    )
    client.crawl("https://e.com", extract_schema={"t": "h1"}, robots_acknowledged_hosts=HOSTS)
    assert _body(crawl)[ACK] == HOSTS
    assert _body(fetch)[ACK] == HOSTS
    assert _body(extract)[ACK] == HOSTS


@respx.mock
def test_the_chat_sends_the_hosts(client: Kloakd) -> None:
    route = respx.post(f"{BASE}/parlyr/chat").mock(
        return_value=Response(
            200,
            text='event: text\ndata: {"type": "text", "content": "ok"}\n\nevent: end\ndata: {}\n\n',
            headers={"content-type": "text/event-stream"},
        )
    )
    client.parlyr.chat("s1", "scrape reddit")
    turn = client.parlyr.chat("s1", "scrape reddit", robots_acknowledged_hosts=HOSTS)
    assert turn.response == "ok"
    assert ACK not in _body(route, 0)
    assert _body(route, 1) == {"session_id": "s1", "message": "scrape reddit", ACK: HOSTS}


@respx.mock
async def test_the_async_chat_and_stream_send_the_hosts(aclient: AsyncKloakd) -> None:
    route = respx.post(f"{BASE}/parlyr/chat").mock(
        return_value=Response(
            200,
            text='event: end\ndata: {}\n\n',
            headers={"content-type": "text/event-stream"},
        )
    )
    await aclient.parlyr.chat("s1", "hi", robots_acknowledged_hosts=HOSTS)
    async with aclient.parlyr.chat_stream("s1", "hi", robots_acknowledged_hosts=HOSTS) as events:
        assert [e async for e in events] == []
    assert _body(route, 0)[ACK] == HOSTS
    assert _body(route, 1)[ACK] == HOSTS


# ── The stop: 409 ROBOTS_DISALLOWED ────────────────────────────────────


@respx.mock
def test_a_stop_is_a_robots_disallowed_error_and_is_not_retried(client: Kloakd) -> None:
    route = respx.post(f"{BASE}/evadr/fetch").mock(
        return_value=Response(409, json={"detail": STOP})
    )
    with pytest.raises(RobotsDisallowedError) as caught:
        client.evadr.fetch("https://www.reddit.com/r/Python/")
    e = caught.value
    assert isinstance(e, KloakdError)
    assert (e.status_code, e.code) == (409, "ROBOTS_DISALLOWED")
    assert (e.reason, e.host, e.rule) == ("disallowed", "www.reddit.com", "Disallow: /")
    assert e.url == "https://www.reddit.com/r/Python/"
    assert e.redirected_from is None
    assert e.terms_version == "draft-2026-11-19"
    assert e.acknowledge_field == "robots_acknowledged_hosts"
    assert e.message == STOP["message"]
    assert route.call_count == 1


@respx.mock
def test_an_unreadable_stop_after_a_redirect(client: Kloakd) -> None:
    detail = {**STOP, "reason": "unreadable", "rule": None, "redirected_from": "https://r.com/"}
    respx.post(f"{BASE}/kolektr/extract").mock(return_value=Response(409, json={"detail": detail}))
    with pytest.raises(RobotsDisallowedError) as caught:
        client.kolektr.page("https://r.com/")
    assert (caught.value.reason, caught.value.rule) == ("unreadable", None)
    assert caught.value.redirected_from == "https://r.com/"


@respx.mock
def test_acknowledging_the_stopped_host_goes_past_it(client: Kloakd) -> None:
    """The README's pattern: catch the stop, ask again naming its host."""
    route = respx.post(f"{BASE}/evadr/scan").mock(
        side_effect=[Response(409, json={"detail": STOP}), mock_response({"ok": True})]
    )
    try:
        client.evadr.scan("https://www.reddit.com/")
    except RobotsDisallowedError as e:
        result = client.evadr.scan("https://www.reddit.com/", robots_acknowledged_hosts=[e.host])
    assert result == {"ok": True}
    assert ACK not in _body(route, 0)
    assert _body(route, 1)[ACK] == ["www.reddit.com"]


@respx.mock
async def test_the_async_client_raises_the_stop(aclient: AsyncKloakd) -> None:
    respx.post(f"{BASE}/webgrph/crawl").mock(return_value=Response(409, json={"detail": STOP}))
    with pytest.raises(RobotsDisallowedError) as caught:
        await aclient.webgrph.start_crawl("https://www.reddit.com/")
    assert caught.value.host == "www.reddit.com"


@respx.mock
def test_another_409_is_unchanged(client: Kloakd) -> None:
    respx.post(f"{BASE}/evadr/scan").mock(
        return_value=Response(409, json={"detail": {"error": "concurrent_limit", "message": "busy", "concurrent_limit": 2}})
    )
    with pytest.raises(ConcurrencyLimitError) as caught:
        client.evadr.scan("https://e.com")
    assert not isinstance(caught.value, RobotsDisallowedError)
    respx.post(f"{BASE}/evadr/profile").mock(
        return_value=Response(409, json={"detail": {"error": "not_continuable", "message": "no"}})
    )
    with pytest.raises(ApiError) as other:
        client.evadr.profile("https://e.com")
    assert not isinstance(other.value, RobotsDisallowedError)


# ── KLOAKD could not ask: 503 ROBOTS_CHECK_UNAVAILABLE ────────────────


def _unavailable(reason: Any = None, retry_after: str = "0") -> Response:
    detail = {
        "error": "ROBOTS_CHECK_UNAVAILABLE",
        "code": "ROBOTS_CHECK_UNAVAILABLE",
        "host": "www.gov.uk",
        "message": "KLOAKD could not read www.gov.uk/robots.txt.",
        "retry_after_s": 30,
    }
    if reason:
        detail["reason"] = reason
    return Response(503, headers={"Retry-After": retry_after}, json={"detail": detail})


@respx.mock
def test_the_check_unavailable_is_retried_after_retry_after(client: Kloakd) -> None:
    route = respx.post(f"{BASE}/evadr/fetch").mock(return_value=_unavailable())
    with pytest.raises(RobotsCheckUnavailableError) as caught:
        client.evadr.fetch("https://www.gov.uk/")
    e = caught.value
    assert not isinstance(e, RobotsExitsRefusedError)
    assert (e.status_code, e.code, e.host, e.reason) == (503, "ROBOTS_CHECK_UNAVAILABLE", "www.gov.uk", None)
    assert e.retry_after == 0
    assert route.call_count == 3  # max_retries attempts, as billing_unavailable


@respx.mock
def test_the_check_unavailable_reads_retry_after_s_without_a_header(client: Kloakd) -> None:
    respx.post(f"{BASE}/evadr/fetch").mock(
        return_value=Response(503, json={"detail": {"error": "ROBOTS_CHECK_UNAVAILABLE", "retry_after_s": 12}})
    )
    one = Kloakd(api_key="k", organization_id=TEST_ORG_ID, base_url=TEST_BASE_URL, max_retries=1)
    with pytest.raises(RobotsCheckUnavailableError) as caught:
        one.evadr.fetch("https://e.com")
    assert caught.value.retry_after == 12


@respx.mock
def test_exits_refused_is_its_own_error_and_is_not_retried(client: Kloakd) -> None:
    route = respx.post(f"{BASE}/evadr/fetch").mock(return_value=_unavailable("exits_refused"))
    with pytest.raises(RobotsExitsRefusedError) as caught:
        client.evadr.fetch("https://www.gov.uk/")
    e = caught.value
    assert isinstance(e, RobotsCheckUnavailableError)
    assert (e.status_code, e.code, e.reason, e.host) == (503, "ROBOTS_CHECK_UNAVAILABLE", "exits_refused", "www.gov.uk")
    assert route.call_count == 1


@respx.mock
async def test_the_async_client_retries_the_one_and_not_the_other(aclient: AsyncKloakd) -> None:
    fetch = respx.post(f"{BASE}/evadr/fetch").mock(return_value=_unavailable())
    scan = respx.post(f"{BASE}/evadr/scan").mock(return_value=_unavailable("exits_refused"))
    with pytest.raises(RobotsCheckUnavailableError):
        await aclient.evadr.fetch("https://www.gov.uk/")
    with pytest.raises(RobotsExitsRefusedError):
        await aclient.evadr.scan("https://www.gov.uk/")
    assert (fetch.call_count, scan.call_count) == (3, 1)
