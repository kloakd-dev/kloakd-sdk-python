"""Crawl estimate, continue with options and the crawl time budget, against
the crawl-estimate contract of 14 November 2026 (CRAWL-ESTIMATE-CONTRACT.md,
sections 1-4; kobe-scraper feature/2026-11-14-crawl-estimate builds the
routes to it).
"""

from __future__ import annotations

import json
from typing import Any

import pytest
import respx
from httpx import Response

from kloakd import (
    ApiError,
    AsyncKloakd,
    CrawlContinueResult,
    CrawlEstimate,
    CrawlEstimatePages,
    CrawlEstimatePlanLimits,
    CrawlEstimateRange,
    CrawlEstimateSite,
    CrawlExtractContinueResult,
    ForbiddenError,
    Kloakd,
)
from tests.conftest import ORG_PREFIX, TEST_BASE_URL, TEST_ORG_ID, mock_response

BASE = f"{TEST_BASE_URL}{ORG_PREFIX}"
CRAWL = f"{BASE}/webgrph/crawl"
CE = f"{BASE}/webgrph/crawl-extract"
URL = "https://example.com/"

# Section 1's example response.
ESTIMATE = {
    "mode": "crawl",
    "url": URL,
    "max_depth": 2,
    "max_pages": 10,
    "plan_limits": {"max_depth": 5, "max_pages": 500, "plan_tier": "free"},
    "clamped": False,
    "site": {
        "reachable": True,
        "sitemap_pages": 1234,
        "homepage_links": 57,
        "probe_error": None,
    },
    "est_pages": {"low": 10, "high": 10, "source": "sitemap"},
    "will_hit_page_cap": True,
    "time_budget_s": 120,
    "est_duration_s": {"low": 40, "high": 120},
    "est_gb": 0.03,
    "gb_remaining": 4.2,
    "will_exhaust_quota": False,
    "warning": None,
    "explanation": (
        "A crawl maps the site: it finds the pages and how they link, "
        "without pulling data from them."
    ),
}


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


# ── 1. Estimate ──


@respx.mock
def test_estimate_crawl_posts_the_url_and_limits_and_reads_every_field(
    client: Kloakd,
) -> None:
    route = respx.post(f"{CRAWL}/estimate").mock(return_value=mock_response(ESTIMATE))
    est = client.webgrph.estimate_crawl(URL, max_depth=2, max_pages=10)
    assert _body(route) == {"url": URL, "max_depth": 2, "max_pages": 10}
    assert est == CrawlEstimate(
        mode="crawl",
        url=URL,
        max_depth=2,
        max_pages=10,
        plan_limits=CrawlEstimatePlanLimits(5, 500, "free"),
        clamped=False,
        site=CrawlEstimateSite(True, 1234, 57, None),
        est_pages=CrawlEstimatePages(10, 10, "sitemap"),
        will_hit_page_cap=True,
        time_budget_s=120,
        est_duration_s=CrawlEstimateRange(40, 120),
        est_gb=0.03,
        gb_remaining=4.2,
        will_exhaust_quota=False,
        warning=None,
        explanation=ESTIMATE["explanation"],
        raw=ESTIMATE,
    )


@respx.mock
def test_estimate_crawl_sends_only_the_url_without_limits(client: Kloakd) -> None:
    route = respx.post(f"{CRAWL}/estimate").mock(return_value=mock_response(ESTIMATE))
    client.webgrph.estimate_crawl(URL)
    assert _body(route) == {"url": URL}


@respx.mock
def test_a_failed_probe_still_parses_with_nulls(client: Kloakd) -> None:
    failed = {
        **ESTIMATE,
        "clamped": True,
        "site": {
            "reachable": False,
            "sitemap_pages": None,
            "homepage_links": None,
            "probe_error": "timeout",
        },
        "est_pages": {"low": 1, "high": 10, "source": "limit"},
        "gb_remaining": None,
        "will_exhaust_quota": True,
        "warning": "This crawl may use the rest of your data.",
    }
    respx.post(f"{CRAWL}/estimate").mock(return_value=mock_response(failed))
    est = client.webgrph.estimate_crawl(URL, max_depth=9)
    assert est.clamped and est.will_exhaust_quota
    assert est.site == CrawlEstimateSite(False, None, None, "timeout")
    assert est.est_pages.source == "limit"
    assert est.gb_remaining is None
    assert est.warning == "This crawl may use the rest of your data."


@respx.mock
def test_estimate_crawl_extract_posts_the_extract_spec(client: Kloakd) -> None:
    body = {
        **ESTIMATE,
        "mode": "crawl_extract",
        "explanation": "Crawl & extract also gets the items on each page.",
    }
    route = respx.post(f"{CE}/estimate").mock(return_value=mock_response(body))
    est = client.webgrph.estimate_crawl_extract(
        URL, max_pages=10, extract={"fields": ["title", "price"]}
    )
    assert _body(route) == {
        "url": URL,
        "max_pages": 10,
        "extract": {"fields": ["title", "price"]},
    }
    assert est.mode == "crawl_extract"


@respx.mock
def test_estimate_crawl_extract_without_kolektr_raises_forbidden(
    client: Kloakd,
) -> None:
    respx.post(f"{CE}/estimate").mock(
        return_value=Response(
            403, json={"detail": {"error": "module_not_entitled", "message": "No"}}
        )
    )
    with pytest.raises(ForbiddenError) as caught:
        client.webgrph.estimate_crawl_extract(URL)
    assert caught.value.code == "module_not_entitled"


@respx.mock
async def test_async_estimates(aclient: AsyncKloakd) -> None:
    crawl = respx.post(f"{CRAWL}/estimate").mock(return_value=mock_response(ESTIMATE))
    ce = respx.post(f"{CE}/estimate").mock(return_value=mock_response(ESTIMATE))
    est = await aclient.webgrph.estimate_crawl(URL, max_pages=10)
    assert est.time_budget_s == 120 and _body(crawl) == {"url": URL, "max_pages": 10}
    await aclient.webgrph.estimate_crawl_extract(URL, max_depth=1)
    assert _body(ce) == {"url": URL, "max_depth": 1}


# ── 3. Continue with options ──


@respx.mock
def test_continue_crawl_with_options_sends_them(client: Kloakd) -> None:
    route = respx.post(f"{CRAWL}/c1/continue").mock(
        return_value=mock_response(
            {"success": True, "crawl_id": "c1", "status": "queued"}, status_code=202
        )
    )
    assert client.webgrph.continue_crawl(
        "c1", max_pages=200, max_depth=3
    ) == CrawlContinueResult(True, "c1", "queued")
    assert _body(route) == {"max_pages": 200, "max_depth": 3}
    client.webgrph.continue_crawl("c1", max_pages=300)
    assert _body(route) == {"max_pages": 300}


@respx.mock
def test_continue_crawl_without_options_sends_no_body(client: Kloakd) -> None:
    route = respx.post(f"{CRAWL}/c1/continue").mock(
        return_value=mock_response({"success": True, "crawl_id": "c1"})
    )
    client.webgrph.continue_crawl("c1")
    assert route.calls[-1].request.content == b""


@respx.mock
def test_continue_crawl_lower_limit_raises_the_422_code(client: Kloakd) -> None:
    respx.post(f"{CRAWL}/c1/continue").mock(
        return_value=Response(422, json={"error": "continue_cannot_lower"})
    )
    with pytest.raises(ApiError) as caught:
        client.webgrph.continue_crawl("c1", max_pages=5)
    assert caught.value.status_code == 422
    assert caught.value.code == "continue_cannot_lower"


@respx.mock
def test_continue_crawl_extract_with_and_without_options(client: Kloakd) -> None:
    route = respx.post(f"{CE}/j%2F1/continue").mock(
        return_value=mock_response(
            {"success": True, "job_id": "j/1", "crawl_id": "c1", "status": "queued"},
            status_code=202,
        )
    )
    assert client.webgrph.continue_crawl_extract("j/1") == CrawlExtractContinueResult(
        True, "j/1", "c1", "queued"
    )
    assert route.calls[-1].request.content == b""
    client.webgrph.continue_crawl_extract("j/1", max_pages=400)
    assert _body(route) == {"max_pages": 400}


@respx.mock
def test_continue_crawl_extract_409_is_raised(client: Kloakd) -> None:
    respx.post(f"{CE}/j1/continue").mock(
        return_value=Response(
            409,
            json={"detail": {"error": "not_continuable", "message": "Not partial"}},
        )
    )
    with pytest.raises(ApiError) as caught:
        client.webgrph.continue_crawl_extract("j1", max_depth=4)
    assert caught.value.status_code == 409
    assert caught.value.code == "not_continuable"


@respx.mock
async def test_async_continue_with_and_without_options(aclient: AsyncKloakd) -> None:
    crawl = respx.post(f"{CRAWL}/c1/continue").mock(
        return_value=mock_response({"success": True, "crawl_id": "c1"})
    )
    ce = respx.post(f"{CE}/j1/continue").mock(
        return_value=mock_response({"success": True, "job_id": "j1"})
    )
    await aclient.webgrph.continue_crawl("c1")
    assert crawl.calls[-1].request.content == b""
    await aclient.webgrph.continue_crawl("c1", max_depth=4)
    assert _body(crawl) == {"max_depth": 4}
    done = await aclient.webgrph.continue_crawl_extract("j1", max_pages=50)
    assert done.job_id == "j1" and _body(ce) == {"max_pages": 50}


# ── 2. Status responses expose the time budget ──


def _crawl_status(**over: Any) -> dict[str, Any]:
    return {
        "crawl_id": "c1", "status": "queued", "organization_id": TEST_ORG_ID,
        "total_pages": 0, "max_depth_reached": 0, **over,
    }


@respx.mock
def test_crawl_status_reads_the_time_budget(client: Kloakd) -> None:
    respx.get(f"{CRAWL}/c1").mock(
        return_value=mock_response(
            _crawl_status(
                status="held_quota", time_budget_s=120, elapsed_s=30.5,
                est_remaining_s=89.5,
            )
        )
    )
    crawl = client.webgrph.wait_for_crawl("c1")
    assert (crawl.time_budget_s, crawl.elapsed_s, crawl.est_remaining_s) == (
        120, 30.5, 89.5,
    )


@respx.mock
def test_crawl_status_time_budget_is_none_until_reported(client: Kloakd) -> None:
    respx.get(f"{CRAWL}/c1").mock(
        return_value=mock_response(
            _crawl_status(
                status="held_quota", time_budget_s=None, elapsed_s=None,
                est_remaining_s=None,
            )
        )
    )
    crawl = client.webgrph.wait_for_crawl("c1")
    assert (crawl.time_budget_s, crawl.elapsed_s, crawl.est_remaining_s) == (
        None, None, None,
    )


@respx.mock
def test_crawl_extract_status_reads_the_time_budget(client: Kloakd) -> None:
    respx.get(f"{CE}/j1").mock(
        side_effect=[
            mock_response(
                {"job_id": "j1", "status": "crawling", "time_budget_s": 600,
                 "elapsed_s": 12, "est_remaining_s": 300.25}
            ),
            mock_response({"job_id": "j1", "status": "queued"}),
        ]
    )
    status = client.webgrph.get_crawl_extract("j1")
    assert (status.time_budget_s, status.elapsed_s, status.est_remaining_s) == (
        600, 12.0, 300.25,
    )
    bare = client.webgrph.get_crawl_extract("j1")
    assert (bare.time_budget_s, bare.elapsed_s, bare.est_remaining_s) == (
        None, None, None,
    )
