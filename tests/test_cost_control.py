"""Cost control: page extras, the data limit, the estimate's data and consent,
map first, and a fetch's stored page, against the cost-control contract of
15 November 2026 (COST-CONTROL-CONTRACT.md, sections 1-5 and 8;
kobe-scraper feature/2026-11-15-cost-control builds the routes to it). The
artifact shapes are those of the built backend (item 8).
"""

from __future__ import annotations

import json
from typing import Any

import pytest
import respx
from httpx import Response

from kloakd import (
    PARTIAL_DATA_LIMIT,
    RESOURCE_EXTRAS,
    ApiError,
    Artifact,
    AsyncKloakd,
    CostAcknowledgementRequiredError,
    CrawlEstimateData,
    CrawlEstimateDataRange,
    ForbiddenError,
    Kloakd,
    SiteMap,
    SiteMapBranch,
)
from tests.conftest import ORG_PREFIX, TEST_BASE_URL, TEST_ORG_ID, mock_response
from tests.test_contract import _live

BASE = f"{TEST_BASE_URL}{ORG_PREFIX}"
CRAWL = f"{BASE}/webgrph/crawl"
CE = f"{BASE}/webgrph/crawl-extract"
URL = "https://example.com/"
ART_ID = "5f0c1d2e-9a3b-4c1d-8e2f-0a1b2c3d4e5f"

NEW_KEYS = {
    "include_resources",
    "max_data_mb",
    "estimate_id",
    "cost_acknowledged",
    "urls",
    "include_paths",
}

# Section 4's example data, added to an estimate.
DATA = {
    "source": "site_profile",
    "per_page_mb": {"typical": 1.2, "high": 4.0},
    "total_mb": {"low": 3.0, "typical": 12.0, "high": 40.0},
    "total_mb_all_resources": {"typical": 30.0, "high": 120.0},
    "saving_mb": {"typical": 18.0, "high": 80.0},
    "by_category_mb_per_page": {
        "document": 0.3, "script": 0.6, "data": 0.1, "images": 1.1,
        "media": 0.0, "fonts": 0.1, "stylesheets": 0.08, "tracking": 0.05,
    },
    "saving_by_category_mb": {
        "images": 11.0, "media": 0.0, "fonts": 1.0, "stylesheets": 0.8,
        "tracking": 0.5,
    },
}
ESTIMATE = {
    "mode": "crawl",
    "url": URL,
    "max_depth": 2,
    "max_pages": 10,
    "est_gb": 0.012,
    "include_resources": [],
    "data": DATA,
    "share_of_remaining": {"typical": 0.01, "high": 0.04},
    "consent_required": True,
    "risks": [
        "Some sites block automated visitors; a page that cannot be fetched "
        "still uses the data received while trying."
    ],
    "suggested_max_data_mb": 40.0,
    "estimate_id": "est.signed.token",
}

SITE_MAP = {
    "url": URL,
    "source": "both",
    "total_urls": 1234,
    "truncated": False,
    "data_used_mb": 0.8,
    "branches": [
        {
            "path": "/products/",
            "url_count": 800,
            "sample_urls": [f"{URL}products/a"],
            "children": [
                {
                    "path": "/products/shoes/",
                    "url_count": 500,
                    "sample_urls": [f"{URL}products/shoes/x"],
                    "children": [],
                }
            ],
        },
        {"path": "other", "url_count": 434, "sample_urls": [], "children": []},
    ],
}

ARTIFACT = {
    "id": ART_ID,
    "type": "FETCHED_CONTENT",
    "url": URL,
    "created_at": "2026-11-15T01:02:03Z",
    "size_bytes": 5120,
    "content_type": "text/html",
    "final_url": f"{URL}home",
    "status_code": 200,
    "verified": True,
    "content_url": f"{ORG_PREFIX}/artifacts/{ART_ID}/content",
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
    content = route.calls[i].request.content
    return json.loads(content) if content else None


def _crawl_status(**over: Any) -> dict[str, Any]:
    return {
        "crawl_id": "c1", "status": "held_quota", "organization_id": TEST_ORG_ID,
        "total_pages": 0, "max_depth_reached": 0, **over,
    }


# ── Request fields (sections 1-5) ──


@respx.mock
def test_start_crawl_sends_every_cost_field(client: Kloakd) -> None:
    route = respx.post(CRAWL).mock(return_value=mock_response({"crawl_id": "c1"}))
    client.webgrph.start_crawl(
        URL,
        max_pages=50,
        include_resources=["images", "fonts"],
        max_data_mb=40.0,
        estimate_id="est.signed.token",
        cost_acknowledged=True,
        urls=[URL, f"{URL}a"],
        include_paths=("/products/",),
    )
    assert _body(route) == {
        "url": URL,
        "max_pages": 50,
        "include_external_links": False,
        "include_resources": ["images", "fonts"],
        "max_data_mb": 40.0,
        "estimate_id": "est.signed.token",
        "cost_acknowledged": True,
        "urls": [URL, f"{URL}a"],
        "include_paths": ["/products/"],
    }


@respx.mock
def test_old_crawl_calls_send_no_new_keys(client: Kloakd) -> None:
    route = respx.post(CRAWL).mock(return_value=mock_response({"crawl_id": "c1"}))
    client.webgrph.start_crawl(URL, 2, 10)
    client.webgrph.crawl(URL, 2, 10, wait=False)
    # False is the default: not sent.
    client.webgrph.start_crawl(URL, cost_acknowledged=False)
    for i in range(3):
        assert not NEW_KEYS & set(_body(route, i))


@respx.mock
def test_crawl_passes_the_cost_fields_and_an_empty_extras_list(
    client: Kloakd,
) -> None:
    route = respx.post(CRAWL).mock(return_value=mock_response({"crawl_id": "c1"}))
    client.webgrph.crawl(URL, include_resources=[], max_data_mb=5, wait=False)
    body = _body(route)
    assert body["include_resources"] == []
    assert body["max_data_mb"] == 5
    assert "cost_acknowledged" not in body


@respx.mock
def test_crawl_extract_sends_every_cost_field_and_old_calls_none(
    client: Kloakd,
) -> None:
    route = respx.post(CE).mock(
        return_value=mock_response(
            {"job_id": "j1", "crawl_id": "c1", "status": "queued"}
        )
    )
    respx.get(f"{CE}/j1").mock(
        return_value=mock_response({"job_id": "j1", "status": "completed"})
    )
    client.webgrph.start_crawl_extract(URL)
    assert not NEW_KEYS & set(_body(route))
    client.webgrph.crawl_extract(
        URL,
        include_resources=["stylesheets"],
        max_data_mb=12.5,
        estimate_id="e",
        cost_acknowledged=True,
        urls=[URL],
        include_paths=["/blog/"],
        poll_interval=0,
    )
    body = _body(route)
    assert {k: body[k] for k in NEW_KEYS} == {
        "include_resources": ["stylesheets"],
        "max_data_mb": 12.5,
        "estimate_id": "e",
        "cost_acknowledged": True,
        "urls": [URL],
        "include_paths": ["/blog/"],
    }


@respx.mock
def test_continue_sends_max_data_mb_and_no_body_without_options(
    client: Kloakd,
) -> None:
    crawl = respx.post(f"{CRAWL}/c1/continue").mock(
        return_value=mock_response({"success": True, "crawl_id": "c1"})
    )
    job = respx.post(f"{CE}/j1/continue").mock(
        return_value=mock_response({"success": True, "job_id": "j1"})
    )
    client.webgrph.continue_crawl("c1", max_data_mb=80)
    client.webgrph.continue_crawl("c1")
    client.webgrph.continue_crawl_extract("j1", max_pages=100, max_data_mb=80.5)
    client.webgrph.continue_crawl_extract("j1")
    assert _body(crawl, 0) == {"max_data_mb": 80}
    assert _body(crawl, 1) is None
    assert _body(job, 0) == {"max_pages": 100, "max_data_mb": 80.5}
    assert _body(job, 1) is None


# ── The estimate (section 4) ──


@respx.mock
def test_estimate_sends_include_resources_and_reads_the_data(
    client: Kloakd,
) -> None:
    route = respx.post(f"{CRAWL}/estimate").mock(return_value=mock_response(ESTIMATE))
    est = client.webgrph.estimate_crawl(URL, max_pages=10, include_resources=["images"])
    assert _body(route) == {
        "url": URL, "max_pages": 10, "include_resources": ["images"],
    }
    assert est.include_resources == []
    assert est.data == CrawlEstimateData(
        source="site_profile",
        per_page_mb=CrawlEstimateDataRange(typical=1.2, high=4.0),
        total_mb=CrawlEstimateDataRange(typical=12.0, high=40.0, low=3.0),
        total_mb_all_resources=CrawlEstimateDataRange(typical=30.0, high=120.0),
        saving_mb=CrawlEstimateDataRange(typical=18.0, high=80.0),
        by_category_mb_per_page=DATA["by_category_mb_per_page"],
        saving_by_category_mb=DATA["saving_by_category_mb"],
    )
    assert est.data.per_page_mb.low is None
    assert est.share_of_remaining == CrawlEstimateDataRange(typical=0.01, high=0.04)
    assert est.consent_required is True
    assert est.risks == ESTIMATE["risks"]
    assert est.suggested_max_data_mb == 40.0
    assert est.estimate_id == "est.signed.token"
    assert est.est_gb == 0.012


@respx.mock
def test_an_estimate_without_the_new_fields_still_parses(client: Kloakd) -> None:
    route = respx.post(f"{CRAWL}/estimate").mock(
        return_value=mock_response({"mode": "crawl", "url": URL})
    )
    est = client.webgrph.estimate_crawl(URL)
    assert _body(route) == {"url": URL}
    assert (est.data, est.share_of_remaining, est.suggested_max_data_mb) == (
        None, None, None,
    )
    assert (est.include_resources, est.risks, est.consent_required) == ([], [], False)
    assert est.estimate_id is None


@respx.mock
def test_estimate_crawl_extract_sends_include_resources(client: Kloakd) -> None:
    route = respx.post(f"{CE}/estimate").mock(return_value=mock_response(ESTIMATE))
    est = client.webgrph.estimate_crawl_extract(
        URL, extract={"fields": ["title"]}, include_resources=[]
    )
    assert _body(route) == {
        "url": URL, "extract": {"fields": ["title"]}, "include_resources": [],
    }
    assert est.data is not None and est.data.source == "site_profile"


@respx.mock
def test_the_consent_409_is_typed_and_not_retried(client: Kloakd) -> None:
    route = respx.post(CRAWL).mock(
        return_value=Response(409, json={"error": "cost_acknowledgement_required"})
    )
    with pytest.raises(CostAcknowledgementRequiredError) as caught:
        client.webgrph.start_crawl(URL)
    assert caught.value.status_code == 409
    assert caught.value.code == "cost_acknowledgement_required"
    assert isinstance(caught.value, ApiError)
    assert route.call_count == 1


@respx.mock
def test_the_consent_409_inside_detail_is_typed_too(client: Kloakd) -> None:
    respx.post(CE).mock(
        return_value=Response(
            409,
            json={"detail": {"error": "cost_acknowledgement_required",
                             "message": "Accept the estimate first."}},
        )
    )
    with pytest.raises(CostAcknowledgementRequiredError, match="Accept the estimate"):
        client.webgrph.start_crawl_extract(URL)


@respx.mock
def test_another_409_is_not_the_consent_error(client: Kloakd) -> None:
    respx.post(f"{CRAWL}/c1/continue").mock(
        return_value=Response(409, json={"detail": {"error": "not_continuable"}})
    )
    with pytest.raises(ApiError) as caught:
        client.webgrph.continue_crawl("c1")
    assert not isinstance(caught.value, CostAcknowledgementRequiredError)


# ── Status (section 3) ──


@respx.mock
def test_crawl_status_reads_the_data_fields(client: Kloakd) -> None:
    respx.get(f"{CRAWL}/c1").mock(
        side_effect=[
            mock_response(
                _crawl_status(
                    data_used_mb=40.2, max_data_mb=40, include_resources=["images"],
                    partial_reason="data_limit",
                )
            ),
            mock_response(_crawl_status()),
        ]
    )
    crawl = client.webgrph.wait_for_crawl("c1")
    assert (crawl.data_used_mb, crawl.max_data_mb, crawl.include_resources) == (
        40.2, 40.0, ["images"],
    )
    assert crawl.partial_reason == PARTIAL_DATA_LIMIT == "data_limit"
    bare = client.webgrph.wait_for_crawl("c1")
    assert (bare.data_used_mb, bare.max_data_mb, bare.include_resources) == (
        None, None, None,
    )


@respx.mock
def test_crawl_extract_status_reads_the_data_fields(client: Kloakd) -> None:
    respx.get(f"{CE}/j1").mock(
        side_effect=[
            mock_response(
                {"job_id": "j1", "status": "crawling", "data_used_mb": 3.5,
                 "max_data_mb": None, "include_resources": []}
            ),
            mock_response({"job_id": "j1", "status": "queued"}),
        ]
    )
    status = client.webgrph.get_crawl_extract("j1")
    assert (status.data_used_mb, status.max_data_mb, status.include_resources) == (
        3.5, None, [],
    )
    bare = client.webgrph.get_crawl_extract("j1")
    assert (bare.data_used_mb, bare.max_data_mb, bare.include_resources) == (
        None, None, None,
    )


def test_the_extras_are_the_contracts_five() -> None:
    assert RESOURCE_EXTRAS == ("images", "media", "fonts", "stylesheets", "tracking")


# ── Map first (section 5) ──


@respx.mock
def test_map_site_posts_the_url_and_reads_the_tree(client: Kloakd) -> None:
    route = respx.post(f"{BASE}/webgrph/map").mock(return_value=mock_response(SITE_MAP))
    site = client.webgrph.map_site(URL, max_urls=5000)
    assert _body(route) == {"url": URL, "max_urls": 5000}
    assert isinstance(site, SiteMap)
    assert (site.url, site.source, site.total_urls, site.truncated) == (
        URL, "both", 1234, False,
    )
    assert site.data_used_mb == 0.8
    assert site.branches[0] == SiteMapBranch(
        path="/products/",
        url_count=800,
        sample_urls=[f"{URL}products/a"],
        children=[
            SiteMapBranch(
                path="/products/shoes/", url_count=500,
                sample_urls=[f"{URL}products/shoes/x"],
            )
        ],
    )
    assert site.branches[1].path == "other"
    assert site.raw == SITE_MAP


@respx.mock
def test_map_site_without_max_urls_sends_only_the_url(client: Kloakd) -> None:
    route = respx.post(f"{BASE}/webgrph/map").mock(
        return_value=mock_response({"branches": None})
    )
    site = client.webgrph.map_site(URL)
    assert _body(route) == {"url": URL}
    assert (site.url, site.branches, site.total_urls) == (URL, [], 0)


# ── A fetch's stored page (section 8) ──


@respx.mock
def test_get_artifact_reads_the_metadata(client: Kloakd) -> None:
    route = respx.get(f"{BASE}/artifacts/{ART_ID}").mock(
        return_value=mock_response(ARTIFACT)
    )
    art = client.get_artifact(ART_ID)
    assert route.called
    assert art == Artifact(
        id=ART_ID,
        type="FETCHED_CONTENT",
        url=URL,
        created_at="2026-11-15T01:02:03Z",
        size_bytes=5120,
        content_type="text/html",
        final_url=f"{URL}home",
        status_code=200,
        verified=True,
        content_url=f"{ORG_PREFIX}/artifacts/{ART_ID}/content",
    )


@respx.mock
def test_a_degraded_artifact_has_null_fields(client: Kloakd) -> None:
    respx.get(f"{BASE}/artifacts/{ART_ID}").mock(
        return_value=mock_response(
            {**ARTIFACT, "type": "DEGRADED_FETCHED_CONTENT", "final_url": None,
             "status_code": None, "verified": False}
        )
    )
    art = client.get_artifact(ART_ID)
    assert art.type == "DEGRADED_FETCHED_CONTENT"
    assert (art.final_url, art.status_code, art.verified) == (None, None, False)


@respx.mock
def test_download_artifact_returns_the_html_bytes(client: Kloakd) -> None:
    html = "<html><body>Héllo</body></html>".encode()
    route = respx.get(f"{BASE}/artifacts/{ART_ID}/content").mock(
        return_value=Response(
            200,
            content=html,
            headers={
                "Content-Type": "text/html; charset=utf-8",
                "Content-Disposition": (
                    'attachment; filename="example.com-5f0c1d2e.html"'
                ),
            },
        )
    )
    assert client.download_artifact(ART_ID) == html
    assert route.called


@respx.mock
def test_the_artifact_id_is_one_path_segment(client: Kloakd) -> None:
    route = respx.get(url__regex=r".*/artifacts/a%2F1$").mock(
        return_value=mock_response({"id": "a/1"})
    )
    assert client.get_artifact("a/1").id == "a/1"
    assert route.called


@respx.mock
def test_artifact_errors(client: Kloakd) -> None:
    respx.get(f"{BASE}/artifacts/{ART_ID}").mock(
        return_value=Response(404, json={"detail": "Artifact not found"})
    )
    respx.get(f"{BASE}/artifacts/{ART_ID}/content").mock(
        return_value=Response(403, json={"detail": "Forbidden"})
    )
    respx.get(f"{BASE}/artifacts/not-a-uuid/content").mock(
        return_value=Response(
            422,
            json={"detail": [{"type": "uuid_parsing", "loc": ["path", "artifact_id"],
                              "msg": "Input should be a valid UUID"}]},
        )
    )
    with pytest.raises(ApiError, match="Artifact not found") as nf:
        client.get_artifact(ART_ID)
    assert nf.value.status_code == 404
    with pytest.raises(ForbiddenError):
        client.download_artifact(ART_ID)
    with pytest.raises(ApiError) as bad:
        client.download_artifact("not-a-uuid")
    assert bad.value.status_code == 422


def test_the_new_routes_are_listed() -> None:
    assert _live("POST", f"{ORG_PREFIX}/webgrph/map")
    assert _live("GET", f"{ORG_PREFIX}/artifacts/{ART_ID}")
    assert _live("GET", f"{ORG_PREFIX}/artifacts/{ART_ID}/content")


# ── Extras off on fetch and extract (owner decision, 15 November 2026) ──


@respx.mock
def test_fetch_and_extract_send_include_resources_only_when_given(
    client: Kloakd,
) -> None:
    fetch = respx.post(f"{BASE}/evadr/fetch").mock(
        return_value=mock_response({"success": True, "url": URL, "status_code": 200})
    )
    extract = respx.post(f"{BASE}/kolektr/extract").mock(
        return_value=mock_response({"success": True, "url": URL, "records": []})
    )
    client.evadr.fetch(URL)
    client.evadr.fetch(URL, force_browser=True, include_resources=["images"])
    client.kolektr.page(URL)
    client.kolektr.page(URL, include_resources=["fonts"])
    client.kolektr.page_all(URL, include_resources=[])
    assert _body(fetch, 0) == {"url": URL}
    assert _body(fetch, 1) == {
        "url": URL, "force_browser": True, "include_resources": ["images"],
    }
    assert "include_resources" not in _body(extract, 0)
    assert _body(extract, 1)["include_resources"] == ["fonts"]
    assert _body(extract, 2)["include_resources"] == []


# ── Async ──


@respx.mock
async def test_async_cost_control(aclient: AsyncKloakd) -> None:
    start = respx.post(CRAWL).mock(return_value=mock_response({"crawl_id": "c1"}))
    est = respx.post(f"{CRAWL}/estimate").mock(return_value=mock_response(ESTIMATE))
    cont = respx.post(f"{CE}/j1/continue").mock(
        return_value=mock_response({"success": True, "job_id": "j1"})
    )
    respx.post(f"{BASE}/webgrph/map").mock(return_value=mock_response(SITE_MAP))
    respx.get(f"{BASE}/artifacts/{ART_ID}").mock(return_value=mock_response(ARTIFACT))
    respx.get(f"{BASE}/artifacts/{ART_ID}/content").mock(
        return_value=Response(200, content=b"<html></html>")
    )
    fetch = respx.post(f"{BASE}/evadr/fetch").mock(
        return_value=mock_response({"success": True, "url": URL, "status_code": 200})
    )

    e = await aclient.webgrph.estimate_crawl(URL, include_resources=["media"])
    assert _body(est) == {"url": URL, "include_resources": ["media"]}
    assert e.consent_required and e.data is not None
    await aclient.webgrph.crawl(
        URL, wait=False, estimate_id=e.estimate_id, cost_acknowledged=True,
        max_data_mb=e.suggested_max_data_mb, include_paths=["/products/"],
    )
    assert _body(start) == {
        "url": URL, "include_external_links": False,
        "estimate_id": "est.signed.token", "cost_acknowledged": True,
        "max_data_mb": 40.0, "include_paths": ["/products/"],
    }
    await aclient.webgrph.continue_crawl_extract("j1", max_data_mb=99)
    assert _body(cont) == {"max_data_mb": 99}
    site = await aclient.webgrph.map_site(URL)
    assert site.branches[0].children[0].url_count == 500
    art = await aclient.get_artifact(ART_ID)
    assert art.verified is True
    assert await aclient.download_artifact(ART_ID) == b"<html></html>"
    await aclient.evadr.fetch(URL, include_resources=["tracking"])
    assert _body(fetch) == {"url": URL, "include_resources": ["tracking"]}


# ── Follow-up for the merged backend (kobe-scraper 964ba78c) ──


@respx.mock
def test_estimate_sends_capture_mode_and_reads_the_locked_extras(
    client: Kloakd,
) -> None:
    crawl = respx.post(f"{CRAWL}/estimate").mock(
        return_value=mock_response(
            {**ESTIMATE, "include_resources": ["images", "stylesheets"],
             "include_resources_locked": ["images", "stylesheets"]}
        )
    )
    ce = respx.post(f"{CE}/estimate").mock(return_value=mock_response(ESTIMATE))
    est = client.webgrph.estimate_crawl(URL, capture_mode="visual")
    assert _body(crawl) == {"url": URL, "capture_mode": "visual"}
    assert est.include_resources == ["images", "stylesheets"]
    assert est.include_resources_locked == ["images", "stylesheets"]
    # An older answer has no locked list.
    older = client.webgrph.estimate_crawl_extract(URL, capture_mode="visual")
    assert _body(ce) == {"url": URL, "capture_mode": "visual"}
    assert older.include_resources_locked is None
    client.webgrph.estimate_crawl(URL)
    assert "capture_mode" not in _body(crawl)


@respx.mock
def test_fetch_async_stream_and_extract_html_send_include_resources(
    client: Kloakd,
) -> None:
    route = respx.post(f"{BASE}/evadr/fetch/async").mock(
        return_value=mock_response({"job_id": "f1"})
    )
    respx.get(f"{BASE}/evadr/jobs/f1/events").mock(
        return_value=Response(
            200, content=b"", headers={"Content-Type": "text/event-stream"}
        )
    )
    html = respx.post(f"{BASE}/kolektr/extract/html").mock(
        return_value=mock_response({"success": True, "url": URL, "records": []})
    )
    client.evadr.fetch_async(URL)
    client.evadr.fetch_async(URL, include_resources=["images"])
    list(client.evadr.fetch_stream(URL, include_resources=["fonts"]))
    client.kolektr.extract_html("<html></html>", URL)
    client.kolektr.extract_html("<html></html>", URL, include_resources=[])
    assert _body(route, 0) == {"url": URL}
    assert _body(route, 1) == {"url": URL, "include_resources": ["images"]}
    assert _body(route, 2) == {"url": URL, "include_resources": ["fonts"]}
    assert "include_resources" not in _body(html, 0)
    assert _body(html, 1)["include_resources"] == []


@respx.mock
def test_continue_crawl_extract_reads_the_202_answer(client: Kloakd) -> None:
    respx.post(f"{CE}/j1/continue").mock(
        return_value=Response(
            202,
            json={
                "success": True, "job_id": "j1", "crawl_id": "c1",
                "status": "crawling",
                "limits": {"max_pages": 500, "max_depth": 3},
                "links": {"self": "/x"},
                "time_budget_s": 900, "elapsed_s": 120.5, "max_data_mb": 80,
            },
        )
    )
    res = client.webgrph.continue_crawl_extract("j1", max_pages=500, max_data_mb=80)
    assert (res.success, res.job_id, res.crawl_id, res.status) == (
        True, "j1", "c1", "crawling",
    )
    assert (res.max_pages, res.max_depth) == (500, 3)
    assert (res.time_budget_s, res.elapsed_s, res.max_data_mb) == (900, 120.5, 80.0)
    assert res.links == {"self": "/x"}


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (409, "continue_needs_more_pages"),
        (409, "continue_needs_more_data"),
        (409, "not_continuable"),
        (409, "already_continuing"),
        (422, "continue_cannot_lower"),
    ],
)
@respx.mock
def test_continue_crawl_extract_errors_carry_their_code(
    client: Kloakd, status: int, code: str
) -> None:
    route = respx.post(f"{CE}/j1/continue").mock(
        return_value=Response(status, json={"detail": {"error": code, "message": "m"}})
    )
    with pytest.raises(ApiError) as caught:
        client.webgrph.continue_crawl_extract("j1", max_pages=10)
    assert (caught.value.status_code, caught.value.code) == (status, code)
    assert not isinstance(caught.value, CostAcknowledgementRequiredError)
    assert route.call_count == 1
