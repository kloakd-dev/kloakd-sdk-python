"""The 0.5.0 fixes, each against the shape kobe-scraper's code sends.

Backend references are paths under kobe-scraper src/kobe_scraper/.
"""

from __future__ import annotations

import inspect
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

import httpx
import pytest
import respx
from httpx import Response

import kloakd._http as http_mod
from kloakd import (
    ApiError,
    AsyncKloakd,
    BillingUnavailableError,
    ConcurrencyLimitError,
    ForbiddenError,
    JobTimeoutError,
    Kloakd,
    NotEntitledError,
    PaymentRequiredError,
    QuotaExceededError,
    RateLimitError,
    UpstreamError,
)
from kloakd._client import _DEFAULT_TIMEOUT
from kloakd._http import raise_for_status
from tests.conftest import ORG_PREFIX, TEST_BASE_URL, TEST_ORG_ID, mock_response

BASE = f"{TEST_BASE_URL}{ORG_PREFIX}"


@pytest.fixture
def waits(monkeypatch: pytest.MonkeyPatch) -> List[float]:
    """Retry waits, recorded instead of slept."""
    out: List[float] = []
    monkeypatch.setattr(http_mod.time, "sleep", out.append)
    return out


@pytest.fixture
def client() -> Kloakd:
    return Kloakd(api_key="sk-test-k", organization_id=TEST_ORG_ID, base_url=TEST_BASE_URL)


def _body(route: Any, i: int = -1) -> Any:
    return json.loads(route.calls[i].request.content)


# ── 1. Default timeout and 17. User-Agent ────────────────────────────────────


def test_default_timeout_is_above_the_85s_sync_wait() -> None:
    # kernel/sync_handoff.py hands off after ~85 s
    assert _DEFAULT_TIMEOUT == 100.0
    assert Kloakd(api_key="k", organization_id="o")._transport._timeout == 100.0
    assert AsyncKloakd(api_key="k", organization_id="o")._transport._timeout == 100.0


@respx.mock
def test_requests_carry_the_user_agent_and_sdk_version(client: Kloakd) -> None:
    route = respx.get(f"{BASE}/skanyr/sites").mock(return_value=mock_response([]))  # type: ignore[arg-type]
    client.skanyr.list_sites()
    headers = route.calls.last.request.headers
    assert headers["user-agent"] == "kloakd-sdk-python/0.5.0"
    assert headers["x-kloakd-sdk"] == "python/0.5.0"


# ── 8. Retries ───────────────────────────────────────────────────────────────


@respx.mock
def test_a_post_answered_500_is_not_repeated(client: Kloakd, waits: List[float]) -> None:
    route = respx.post(f"{BASE}/evadr/scan").mock(return_value=Response(500, json={"detail": "boom"}))
    with pytest.raises(ApiError):
        client.evadr.scan("https://e.com")
    assert route.call_count == 1 and waits == []


@respx.mock
def test_a_get_answered_502_is_retried(client: Kloakd, waits: List[float]) -> None:
    route = respx.get(f"{BASE}/skanyr/sites").mock(
        side_effect=[Response(502, json={"detail": "x"}), Response(200, json=[])]
    )
    assert client.skanyr.list_sites() == []
    assert route.call_count == 2 and waits == [1.0]


@respx.mock
def test_a_delete_answered_503_is_retried(client: Kloakd, waits: List[float]) -> None:
    route = respx.delete(f"{BASE}/skanyr/sites/s1").mock(
        side_effect=[Response(503, json={"detail": "x"}), Response(200, json={"site_id": "s1", "deleted": True})]
    )
    client.skanyr.delete_site("s1")
    assert route.call_count == 2


@respx.mock
def test_a_network_error_on_get_is_retried_but_not_on_post(client: Kloakd, waits: List[float]) -> None:
    get = respx.get(f"{BASE}/skanyr/sites").mock(
        side_effect=[httpx.ConnectError("down"), Response(200, json=[])]
    )
    assert client.skanyr.list_sites() == []
    assert get.call_count == 2
    post = respx.post(f"{BASE}/evadr/scan").mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(httpx.ReadTimeout):
        client.evadr.scan("https://e.com")
    assert post.call_count == 1


@respx.mock
def test_a_post_rate_limited_is_retried_after_retry_after(client: Kloakd, waits: List[float]) -> None:
    # kernel/gateway/errors.py RateLimitedError.to_dict() + rate_limit_exceeded_headers
    limited = Response(
        429,
        json={"detail": {"error": "rate_limited", "message": "m", "retry_after": 7, "reset_at": "2099-01-01T00:00:00+00:00"}},
        headers={"Retry-After": "7"},
    )
    route = respx.post(f"{BASE}/evadr/scan").mock(side_effect=[limited, Response(200, json={"ok": 1})])
    assert client.evadr.scan("https://e.com") == {"ok": 1}
    assert route.call_count == 2 and waits == [7.0]


def test_rate_limit_without_retry_after_waits_until_reset_at() -> None:
    reset = (datetime.now(timezone.utc) + timedelta(seconds=20)).isoformat()
    with pytest.raises(RateLimitError) as e:
        raise_for_status(429, b"", {"detail": {"error": "rate_limited", "reset_at": reset}})
    assert 18 <= e.value.retry_after <= 21
    assert not e.value.quota_exhausted


@respx.mock
def test_the_playground_quota_is_not_retried(client: Kloakd, waits: List[float]) -> None:
    # kernel/gateway/rate_limiter.py: test keys over quota get retry_after=0, reset_at=""
    quota = Response(
        429,
        json={"detail": {"error": "rate_limited", "message": "m", "retry_after": 0, "reset_at": "",
                         "quota_used": 50, "quota_limit": 50, "upgrade_url": "https://app.kloakd.dev/pricing"}},
        headers={"Retry-After": "0", "X-Quota-Used": "50", "X-Quota-Limit": "50"},
    )
    route = respx.post(f"{BASE}/evadr/scan").mock(return_value=quota)
    with pytest.raises(RateLimitError) as e:
        client.evadr.scan("https://e.com")
    assert route.call_count == 1 and waits == []
    assert e.value.quota_exhausted
    assert e.value.code == "rate_limited"
    assert (e.value.quota_used, e.value.quota_limit) == (50, 50)
    assert e.value.upgrade_url == "https://app.kloakd.dev/pricing"


@respx.mock
def test_a_post_billing_unavailable_is_retried(client: Kloakd, waits: List[float]) -> None:
    # billing/quota_middleware.py _billing_unavailable: 503, Retry-After 30
    unavailable = Response(
        503,
        json={"detail": {"error": "billing_unavailable", "message": "m", "reason": "check_failed"}},
        headers={"Retry-After": "30"},
    )
    route = respx.post(f"{BASE}/evadr/scan").mock(side_effect=[unavailable, Response(200, json={})])
    client.evadr.scan("https://e.com")
    assert route.call_count == 2 and waits == [30.0]


@respx.mock
async def test_the_async_transport_follows_the_same_retry_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    slept: List[float] = []

    async def fake_sleep(s: float) -> None:
        slept.append(s)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    c = AsyncKloakd(api_key="k", organization_id=TEST_ORG_ID, base_url=TEST_BASE_URL)
    post = respx.post(f"{BASE}/evadr/scan").mock(return_value=Response(500, json={"detail": "x"}))
    with pytest.raises(ApiError):
        await c.evadr.scan("https://e.com")
    assert post.call_count == 1
    get = respx.get(f"{BASE}/skanyr/sites").mock(side_effect=[httpx.ConnectError("x"), Response(200, json=[])])
    assert await c.skanyr.list_sites() == []
    assert get.call_count == 2 and slept == [1.0]


# ── 11. Errors ───────────────────────────────────────────────────────────────


def test_409_concurrent_limit_is_typed() -> None:
    # kernel/gateway/dependencies.py check_concurrent_quota
    body = {"detail": {"error": "concurrent_limit", "message": "Concurrent crawl limit reached (3 for free tier).",
                       "tier": "free", "concurrent_limit": 3, "active_crawls": 3}}
    with pytest.raises(ConcurrencyLimitError) as e:
        raise_for_status(409, b"", body)
    assert e.value.status_code == 409
    assert (e.value.concurrent_limit, e.value.active_crawls, e.value.tier) == (3, 3, "free")
    assert "Concurrent crawl limit" in e.value.message
    assert e.value.code == "concurrent_limit"


def test_other_409s_stay_api_errors() -> None:
    with pytest.raises(ApiError):
        raise_for_status(409, b'{"detail": "exists"}')


def test_tier_access_denied_reads_feature() -> None:
    # billing/tier_policy.py TierAccessDenied.to_dict()
    body = {"detail": {"error": "tier_access_denied", "current_tier": "free", "required_tier": "pro",
                       "feature": "api_access", "message": "API access needs Pro", "upgrade_url": "https://u"}}
    with pytest.raises(NotEntitledError) as e:
        raise_for_status(403, b"", body)
    err = e.value
    assert isinstance(err, ForbiddenError)
    assert (err.code, err.feature, err.module) == ("tier_access_denied", "api_access", "api_access")
    assert (err.current_tier, err.required_tier, err.upgrade_url) == ("free", "pro", "https://u")


@respx.mock
def test_a_non_json_error_body_becomes_the_message(client: Kloakd, waits: List[float]) -> None:
    respx.post(f"{BASE}/evadr/scan").mock(return_value=Response(502, text="<html>Bad gateway</html>"))
    with pytest.raises(UpstreamError) as e:
        client.evadr.scan("https://e.com")
    assert "Bad gateway" in e.value.message


def test_a_422_keeps_the_validation_messages() -> None:
    body = {"detail": [{"loc": ["body", "url"], "msg": "field required", "type": "missing"},
                       {"loc": ["query", "limit"], "msg": "must be <= 10000", "type": "le"}]}
    with pytest.raises(ApiError) as e:
        raise_for_status(422, json.dumps(body).encode())
    assert "url: field required" in e.value.message
    assert "query.limit: must be <= 10000" in e.value.message


def test_402_and_gb_exhausted_are_not_retried() -> None:
    assert not http_mod._is_retryable(PaymentRequiredError("x"), "GET")
    assert not http_mod._is_retryable(QuotaExceededError("x"), "GET")
    assert http_mod._is_retryable(BillingUnavailableError("x"), "POST")


# ── 9. Result fields ─────────────────────────────────────────────────────────


@respx.mock
def test_fetch_result_carries_auth_required_and_discovery_id(client: Kloakd) -> None:
    # modules/evadr/router.py FetchResponse: html is None when auth_required
    respx.post(f"{BASE}/evadr/fetch").mock(return_value=mock_response({
        "success": True, "url": "https://e.com/login", "status_code": 200, "tier_used": 1,
        "html": None, "auth_required": True, "discovery_id": "d-1",
    }))
    r = client.evadr.fetch("https://e.com/login")
    assert (r.auth_required, r.discovery_id, r.html) == (True, "d-1", None)


@respx.mock
def test_extraction_result_carries_auth_required_and_discovery_id(client: Kloakd) -> None:
    # modules/kolektr/router.py ExtractResponse
    respx.post(f"{BASE}/kolektr/extract").mock(return_value=mock_response({
        "success": False, "url": "https://e.com", "method": "auth_chain", "auth_required": True, "discovery_id": "d-2",
    }))
    r = client.kolektr.page("https://e.com")
    assert (r.auth_required, r.discovery_id) == (True, "d-2")


# ── 3. Extraction schema ─────────────────────────────────────────────────────


@respx.mock
def test_schema_shorthand_with_and_without_prefix(client: Kloakd) -> None:
    route = respx.post(f"{BASE}/kolektr/extract").mock(return_value=mock_response({"success": True, "url": "u", "method": "m"}))
    client.kolektr.page("https://e.com", schema={"title": "css:h1", "price": "p.price", "x": "a[href*='css:']"})
    assert _body(route)["schema_spec"] == {"fields": [
        {"name": "title", "selector": "h1"},
        {"name": "price", "selector": "p.price"},
        {"name": "x", "selector": "a[href*='css:']"},
    ]}


@respx.mock
def test_schema_as_a_fields_list_or_full_spec(client: Kloakd) -> None:
    route = respx.post(f"{BASE}/kolektr/extract").mock(return_value=mock_response({"success": True, "url": "u", "method": "m"}))
    fields = [{"name": "link", "selector": "a", "attribute": "href"}]
    client.kolektr.page("https://e.com", schema=fields)
    assert _body(route)["schema_spec"] == {"fields": fields}
    spec = {"fields": fields, "pagination": True, "max_pages": 3}
    client.kolektr.page("https://e.com", schema=spec)
    assert _body(route)["schema_spec"] == spec


# ── 5. skanyr.update_site, Python extras: list parsing, export bytes ─────────


@respx.mock
def test_update_site_sends_the_policy_string(client: Kloakd) -> None:
    # modules/skanyr/router.py SiteUpdateRequest: policy: str
    route = respx.patch(f"{BASE}/skanyr/sites/s1").mock(return_value=mock_response({"site_id": "s1"}))
    client.skanyr.update_site("s1", "head_first")
    assert _body(route) == {"policy": "head_first"}


@respx.mock
def test_skanyr_list_routes_parse_as_lists(client: Kloakd) -> None:
    rows = [{"id": "r1"}]
    for path in ("sites/s1/apis", "sites/s1/resources", "sites/s1/findings", "sites/s1/technologies", "resources"):
        respx.get(f"{BASE}/skanyr/{path}").mock(return_value=Response(200, json=rows))
    assert client.skanyr.get_site_apis("s1") == rows
    assert client.skanyr.get_site_resources("s1") == rows
    assert client.skanyr.get_findings("s1") == rows
    assert client.skanyr.get_technologies("s1") == rows
    assert client.skanyr.list_resources(site_id="s1") == rows


@respx.mock
async def test_async_skanyr_list_routes_parse_as_lists() -> None:
    c = AsyncKloakd(api_key="k", organization_id=TEST_ORG_ID, base_url=TEST_BASE_URL)
    rows = [{"id": "r1"}]
    for path in ("sites/s1/apis", "sites/s1/resources", "sites/s1/findings", "sites/s1/technologies", "resources"):
        respx.get(f"{BASE}/skanyr/{path}").mock(return_value=Response(200, json=rows))
    assert await c.skanyr.get_site_apis("s1") == rows
    assert await c.skanyr.get_site_resources("s1") == rows
    assert await c.skanyr.get_findings("s1") == rows
    assert await c.skanyr.get_technologies("s1") == rows
    assert await c.skanyr.list_resources() == rows


@respx.mock
def test_export_site_returns_the_zip_bytes(client: Kloakd) -> None:
    zip_bytes = b"PK\x03\x04binary\x00\xff"
    route = respx.post(f"{BASE}/skanyr/sites/s1/export").mock(
        return_value=Response(200, content=zip_bytes, headers={"content-type": "application/zip"})
    )
    assert client.skanyr.export_site("s1", resource_ids=["r1"]) == zip_bytes
    assert _body(route) == {"resource_ids": ["r1"]}


@respx.mock
async def test_async_export_site_returns_the_zip_bytes() -> None:
    c = AsyncKloakd(api_key="k", organization_id=TEST_ORG_ID, base_url=TEST_BASE_URL)
    respx.post(f"{BASE}/skanyr/sites/s1/export").mock(return_value=Response(200, content=b"PK\x03\x04"))
    assert await c.skanyr.export_site("s1") == b"PK\x03\x04"


@respx.mock
def test_extraction_text_is_the_plain_text_body(client: Kloakd) -> None:
    # modules/skanyr/router.py get_extracted_text: PlainTextResponse
    respx.get(f"{BASE}/skanyr/extractions/h1/text").mock(
        return_value=Response(200, text="Hello world", headers={"content-type": "text/plain"})
    )
    assert client.skanyr.get_extraction_text("h1") == "Hello world"


# ── 4, 6, 13, 14. Request shapes ─────────────────────────────────────────────


@respx.mock
def test_multi_site_dependencies_are_a_list(client: Kloakd) -> None:
    route = respx.post(f"{BASE}/fetchyr/multi-site-workflows").mock(return_value=mock_response({"id": "w"}))
    deps = [{"dependent_site": "b", "dependency_site": "a", "dependency_type": "sequential"}]
    client.fetchyr.create_multi_site_workflow(
        "n", [{"site_id": "a", "name": "A", "url": "u"}], description="d", dependencies=deps, global_config={"k": 1}
    )
    assert _body(route) == {"name": "n", "sites": [{"site_id": "a", "name": "A", "url": "u"}],
                            "description": "d", "dependencies": deps, "global_config": {"k": 1}}


@respx.mock
def test_list_calls_send_their_paging_parameters(client: Kloakd) -> None:
    jobs = respx.get(f"{BASE}/kolektr/jobs").mock(return_value=mock_response({}))
    scrapers = respx.get(f"{BASE}/kolektr/scrapers").mock(return_value=mock_response({}))
    content = respx.get(f"{BASE}/kolektr/content").mock(return_value=mock_response({}))
    workflows = respx.get(f"{BASE}/fetchyr/workflows").mock(return_value=mock_response({}))
    client.kolektr.list_jobs(page=2, limit=5, status_filter="completed")
    client.kolektr.list_scrapers(page=3, page_size=10, is_template=False)
    client.kolektr.list_content(page=1, page_size=50, search="shoe")
    client.fetchyr.list_workflows(page=4, page_size=25)
    assert dict(jobs.calls.last.request.url.params) == {"page": "2", "limit": "5", "status_filter": "completed"}
    assert dict(scrapers.calls.last.request.url.params) == {"page": "3", "page_size": "10", "is_template": "false"}
    assert dict(content.calls.last.request.url.params) == {"page": "1", "page_size": "50", "search": "shoe"}
    assert dict(workflows.calls.last.request.url.params) == {"page": "4", "page_size": "25"}
    client.kolektr.list_jobs()
    assert dict(jobs.calls.last.request.url.params) == {}


@respx.mock
def test_api_data_endpoint_is_one_encoded_segment(client: Kloakd) -> None:
    endpoint = "https://api.shop.com/v1/items?page=2"
    encoded = "https%3A%2F%2Fapi.shop.com%2Fv1%2Fitems%3Fpage%3D2"
    get = respx.get(url__startswith=f"{BASE}/kolektr/api-data/").mock(return_value=mock_response({}))
    post = respx.post(url__startswith=f"{BASE}/kolektr/api-data/").mock(return_value=mock_response({}))
    client.kolektr.get_api_data(endpoint, endpoint_hash="h")
    assert get.calls.last.request.url.raw_path.decode() == f"{ORG_PREFIX}/kolektr/api-data/{encoded}?endpoint_hash=h"
    client.kolektr.get_api_data_paginated(endpoint, offset=10, limit=5)
    assert get.calls.last.request.url.raw_path.decode().startswith(f"{ORG_PREFIX}/kolektr/api-data/{encoded}/paginated?")
    client.kolektr.extract_all_api_data(endpoint, endpoint_hash="h", max_records=100)
    url = post.calls.last.request.url
    assert url.raw_path.decode().startswith(f"{ORG_PREFIX}/kolektr/api-data/{encoded}/extract-all?")
    assert dict(url.params) == {"endpoint_hash": "h", "max_records": "100"}


@respx.mock
def test_path_ids_are_encoded(client: Kloakd) -> None:
    route = respx.get(url__startswith=f"{BASE}/skanyr/sites/").mock(return_value=mock_response({}))
    client.skanyr.get_site("a/b?c")
    assert route.calls.last.request.url.raw_path.decode() == f"{ORG_PREFIX}/skanyr/sites/a%2Fb%3Fc"


@respx.mock
def test_list_sessions_always_sends_active_only(client: Kloakd) -> None:
    route = respx.get(f"{BASE}/webgrph/sessions").mock(return_value=Response(200, json=[]))
    client.webgrph.list_sessions()
    assert route.calls.last.request.url.params["active_only"] == "true"
    client.webgrph.list_sessions(active_only=False)
    assert route.calls.last.request.url.params["active_only"] == "false"


# ── 7. Crawl helper ──────────────────────────────────────────────────────────


def _mock_crawl(status: str, error: Any = None) -> None:
    respx.post(f"{BASE}/webgrph/crawl").mock(return_value=Response(202, json={"crawl_id": "c1"}))
    respx.get(f"{BASE}/webgrph/crawl/c1").mock(return_value=mock_response(
        {"crawl_id": "c1", "status": status, "total_pages": 2, "error": error}
    ))
    respx.get(f"{BASE}/webgrph/crawl/c1/pages").mock(return_value=mock_response(
        {"nodes": [{"url": "https://e.com/a", "depth": 1}, {"url": "https://e.com/b", "depth": 1}], "next_cursor": None}
    ))


@respx.mock
def test_crawl_reports_the_crawls_own_failure(client: Kloakd) -> None:
    _mock_crawl("failed", "robots.txt disallows")
    r = client.crawl("https://e.com", poll_interval=0)
    assert r.success is False and r.error == "robots.txt disallows"
    assert r.pages == []


@respx.mock
def test_crawl_marks_a_page_failed_but_raises_billing_errors(client: Kloakd, waits: List[float]) -> None:
    _mock_crawl("completed")
    page = {"success": True, "url": "https://e.com/a", "status_code": 200, "tier_used": 1, "html": "<p/>"}
    respx.post(f"{BASE}/evadr/fetch").mock(side_effect=[
        mock_response(page), Response(500, json={"detail": "boom"}),
    ])
    r = client.crawl("https://e.com", poll_interval=0)
    assert r.success is True and r.error is None
    assert (r.pages_fetched, r.pages_failed) == (1, 1)
    assert "boom" in (r.pages[1].error or "")

    respx.post(f"{BASE}/evadr/fetch").mock(return_value=Response(
        429, json={"detail": {"error": "gb_exhausted", "message": "used up", "tier": "free"}}
    ))
    with pytest.raises(QuotaExceededError):
        client.crawl("https://e.com", poll_interval=0)
    with pytest.raises(QuotaExceededError):
        list(client.crawl_stream("https://e.com", poll_interval=0))


@respx.mock
async def test_async_crawl_raises_billing_errors_and_reports_success() -> None:
    c = AsyncKloakd(api_key="k", organization_id=TEST_ORG_ID, base_url=TEST_BASE_URL)
    _mock_crawl("completed")
    respx.post(f"{BASE}/evadr/fetch").mock(return_value=Response(402, json={"detail": {"error": "payment_required", "message": "pay"}}))
    with pytest.raises(PaymentRequiredError):
        await c.crawl("https://e.com", poll_interval=0)
    with pytest.raises(PaymentRequiredError):
        [e async for e in c.crawl_stream("https://e.com", poll_interval=0)]


@respx.mock
async def test_async_crawl_stream_reports_the_crawls_failure() -> None:
    c = AsyncKloakd(api_key="k", organization_id=TEST_ORG_ID, base_url=TEST_BASE_URL)
    _mock_crawl("failed", "nope")
    events = [e async for e in c.crawl_stream("https://e.com", poll_interval=0)]
    done = events[-1]
    assert done.type == "crawl_complete" and done.success is False and done.error == "nope"
    assert done.metadata["result"].success is False


@respx.mock
def test_crawl_stream_reports_the_crawls_failure(client: Kloakd) -> None:
    _mock_crawl("cancelled")
    events = list(client.crawl_stream("https://e.com", poll_interval=0))
    assert [e.type for e in events] == ["discovery_started", "discovery_complete", "crawl_complete"]
    assert events[-1].success is False and events[-1].error == "Crawl cancelled"


@respx.mock
def test_crawl_extracts_with_the_shorthand_schema(client: Kloakd) -> None:
    _mock_crawl("completed")
    page = {"success": True, "url": "https://e.com/a", "status_code": 200, "tier_used": 1, "artifact": {"artifact_id": "f1"}}
    respx.post(f"{BASE}/evadr/fetch").mock(return_value=mock_response(page))
    extract = respx.post(f"{BASE}/kolektr/extract").mock(return_value=mock_response(
        {"success": True, "url": "u", "method": "m", "records": [{"title": "T"}]}
    ))
    r = client.crawl("https://e.com", extract_schema={"title": "css:h1"}, poll_interval=0)
    assert r.pages[0].structured_data == {"title": "T"}
    assert _body(extract)["schema_spec"] == {"fields": [{"name": "title", "selector": "h1"}]}
    assert _body(extract)["fetch_artifact_id"] == "f1"


# ── 12. Hand-off ─────────────────────────────────────────────────────────────


@respx.mock
def test_get_and_wait_for_handoff(client: Kloakd, waits: List[float]) -> None:
    # kernel/sync_handoff.py poll_handoff
    route = respx.get(f"{BASE}/handoff/h-1").mock(side_effect=[
        mock_response({"job_id": "h-1", "status": "running"}),
        mock_response({"job_id": "h-1", "status": "running"}),
        mock_response({"job_id": "h-1", "status": "completed", "result": {"records": [1]}}),
    ])
    assert client.get_handoff("h-1")["status"] == "running"
    assert client.wait_for_handoff("h-1", poll_interval=0.01) == {"records": [1]}
    assert route.call_count == 3


@respx.mock
def test_wait_for_handoff_times_out_with_the_job_id(client: Kloakd, waits: List[float]) -> None:
    with pytest.raises(JobTimeoutError) as e:
        client.wait_for_handoff("h-9", poll_interval=5, timeout=1)
    assert e.value.job_id == "h-9"


@respx.mock
async def test_async_get_and_wait_for_handoff(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    c = AsyncKloakd(api_key="k", organization_id=TEST_ORG_ID, base_url=TEST_BASE_URL)
    respx.get(f"{BASE}/handoff/h-2").mock(side_effect=[
        mock_response({"job_id": "h-2", "status": "running"}),
        mock_response({"job_id": "h-2", "status": "completed", "result": {"ok": True}}),
    ])
    assert (await c.get_handoff("h-2"))["status"] == "running"
    assert await c.wait_for_handoff("h-2", poll_interval=0.01) == {"ok": True}


# ── Package ──────────────────────────────────────────────────────────────────


def test_py_typed_ships_in_the_package() -> None:
    import kloakd

    assert (Path(kloakd.__file__).parent / "py.typed").is_file()
    pyproject = (Path(__file__).parent.parent / "pyproject.toml").read_text()
    assert 'path = "kloakd/py.typed"' in pyproject
    assert 'version = "0.5.0"' in pyproject
    assert kloakd.__version__ == "0.5.0"


def _signature(fn: Any) -> Dict[str, Any]:
    return {n: (p.kind, p.default) for n, p in inspect.signature(fn).parameters.items()}


def test_sync_and_async_signatures_match() -> None:
    sync = Kloakd(api_key="k", organization_id="o")
    aio = AsyncKloakd(api_key="k", organization_id="o")
    pairs = [(type(sync), type(aio))] + [
        (type(getattr(sync, ns)), type(getattr(aio, ns)))
        for ns in ("evadr", "webgrph", "skanyr", "nexus", "parlyr", "fetchyr", "kolektr")
    ]
    for s_cls, a_cls in pairs:
        names = [n for n, _ in inspect.getmembers(s_cls, inspect.isfunction) if not n.startswith("_")]
        for name in names:
            assert _signature(getattr(s_cls, name)) == _signature(getattr(a_cls, name)), f"{s_cls.__name__}.{name}"
