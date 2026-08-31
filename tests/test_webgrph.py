"""Tests for the Webgrph namespace."""

from __future__ import annotations

import pytest
import respx

from kloakd import CrawlResult, Kloakd, PageNode, SiteCrawlResult
from tests.conftest import TEST_BASE_URL, TEST_ORG_ID, ORG_PREFIX, mock_response


@pytest.fixture
def client() -> Kloakd:
    return Kloakd(api_key="sk-test-key", organization_id=TEST_ORG_ID, base_url=TEST_BASE_URL)


@respx.mock
def test_crawl_success(client: Kloakd) -> None:
    respx.post(f"{TEST_BASE_URL}{ORG_PREFIX}/webgrph/crawl").mock(
        return_value=mock_response({
            "success": True,
            "crawl_id": "crawl-001",
            "url": "https://example.com",
            "total_pages": 0,
            "max_depth_reached": 0,
            "artifact_id": None,
            "error": None,
        }, status_code=202)
    )
    respx.get(f"{TEST_BASE_URL}{ORG_PREFIX}/webgrph/crawl/crawl-001").mock(
        return_value=mock_response({
            "crawl_id": "crawl-001",
            "status": "completed",
            "organization_id": TEST_ORG_ID,
            "total_pages": 2,
            "max_depth_reached": 1,
            "artifact_id": "art-hierarchy-001",
            "error": None,
            "graph_data": None,
        })
    )
    respx.get(f"{TEST_BASE_URL}{ORG_PREFIX}/webgrph/crawl/crawl-001/pages").mock(
        return_value=mock_response({
            "crawl_id": "crawl-001",
            "nodes": [
                {"id": "n1", "url": "https://example.com", "depth": 0, "category": "page", "children_urls": [], "classification_confidence": 0.0, "metadata": {"title": "Home"}},
                {"id": "n2", "url": "https://example.com/about", "depth": 1, "category": "page", "children_urls": [], "classification_confidence": 0.0, "metadata": {"title": "About"}},
            ],
            "next_cursor": None,
            "total": 2,
        })
    )
    result = client.webgrph.crawl("https://example.com", max_depth=2, poll_interval=0.01)
    assert isinstance(result, CrawlResult)
    assert result.success is True
    assert result.total_pages == 2
    assert result.artifact_id == "art-hierarchy-001"
    assert len(result.pages) == 2
    assert isinstance(result.pages[0], PageNode)
    assert result.pages[0].title == "Home"
    assert result.ok is True


@respx.mock
def test_get_hierarchy(client: Kloakd) -> None:
    respx.get(f"{TEST_BASE_URL}{ORG_PREFIX}/webgrph/hierarchy/art-001").mock(
        return_value=mock_response({"artifact_id": "art-001", "pages": []})
    )
    result = client.webgrph.get_hierarchy("art-001")
    assert result["artifact_id"] == "art-001"


@respx.mock
def test_get_job(client: Kloakd) -> None:
    respx.get(f"{TEST_BASE_URL}{ORG_PREFIX}/webgrph/jobs/job-001").mock(
        return_value=mock_response({"job_id": "job-001", "status": "completed"})
    )
    result = client.webgrph.get_job("job-001")
    assert result["status"] == "completed"


@respx.mock
def test_crawl_all_autopaginates(client: Kloakd) -> None:
    respx.post(f"{TEST_BASE_URL}{ORG_PREFIX}/webgrph/crawl").mock(
        return_value=mock_response({
            "success": True, "crawl_id": "c1", "url": "https://ex.com",
            "total_pages": 0, "max_depth_reached": 0, "artifact_id": None, "error": None,
        }, status_code=202)
    )
    respx.get(f"{TEST_BASE_URL}{ORG_PREFIX}/webgrph/crawl/c1").mock(
        return_value=mock_response({
            "crawl_id": "c1", "status": "completed", "organization_id": TEST_ORG_ID,
            "total_pages": 2, "max_depth_reached": 0, "artifact_id": None, "error": None, "graph_data": None,
        })
    )

    page_count = 0
    def paginate_pages(request, **kwargs):
        nonlocal page_count
        cursor = request.url.params.get("cursor")
        start = int(cursor) if cursor else 0
        page = {"id": f"n{start}", "url": f"https://ex.com/page{start}", "depth": 0, "category": "page", "children_urls": [], "classification_confidence": 0.0, "metadata": {"title": f"Page {start}"}}
        page_count += 1
        next_cursor = str(start + 1) if start < 1 else None
        return mock_response({"crawl_id": "c1", "nodes": [page], "next_cursor": next_cursor, "total": 2})

    respx.get(url__startswith=f"{TEST_BASE_URL}{ORG_PREFIX}/webgrph/crawl/c1/pages").mock(side_effect=paginate_pages)
    pages = client.webgrph.crawl_all("https://ex.com", poll_interval=0.01)
    assert len(pages) == 2
    assert page_count == 2


@respx.mock
def test_orchestrator_crawl(client: Kloakd) -> None:
    respx.post(f"{TEST_BASE_URL}{ORG_PREFIX}/webgrph/crawl").mock(
        return_value=mock_response({
            "success": True, "crawl_id": "c-orch-sync", "url": "https://example.com",
            "total_pages": 0, "max_depth_reached": 0, "artifact_id": None, "error": None,
        }, status_code=202)
    )
    respx.get(f"{TEST_BASE_URL}{ORG_PREFIX}/webgrph/crawl/c-orch-sync").mock(
        return_value=mock_response({
            "crawl_id": "c-orch-sync", "status": "completed", "organization_id": TEST_ORG_ID,
            "total_pages": 1, "max_depth_reached": 0, "artifact_id": "art-orch-sync",
            "error": None, "graph_data": None,
        })
    )
    respx.get(f"{TEST_BASE_URL}{ORG_PREFIX}/webgrph/crawl/c-orch-sync/pages").mock(
        return_value=mock_response({
            "crawl_id": "c-orch-sync",
            "nodes": [
                {"id": "n1", "url": "https://example.com", "depth": 0, "category": "page", "children_urls": [], "classification_confidence": 0.0, "metadata": {"title": "Home"}},
            ],
            "next_cursor": None, "total": 1,
        })
    )
    respx.post(f"{TEST_BASE_URL}{ORG_PREFIX}/evadr/fetch").mock(
        return_value=mock_response({
            "success": True, "url": "https://example.com", "status_code": 200,
            "tier_used": 1, "html": "<html>sync</html>", "vendor_detected": None,
            "anti_bot_bypassed": False, "artifact_id": "art-fetch-sync", "error": None,
        })
    )
    result = client.crawl("https://example.com", max_depth=1, poll_interval=0.01)
    assert isinstance(result, SiteCrawlResult)
    assert result.success is True
    assert result.total_pages_discovered == 1
    assert result.pages_fetched == 1
    assert len(result.pages) == 1
    assert result.pages[0].html == "<html>sync</html>"
    assert result.crawl_artifact_id == "art-orch-sync"


@respx.mock
def test_orchestrator_crawl_stream(client: Kloakd) -> None:
    respx.post(f"{TEST_BASE_URL}{ORG_PREFIX}/webgrph/crawl").mock(
        return_value=mock_response({
            "success": True, "crawl_id": "c-stream-sync", "url": "https://example.com",
            "total_pages": 0, "max_depth_reached": 0, "artifact_id": None, "error": None,
        }, status_code=202)
    )
    respx.get(f"{TEST_BASE_URL}{ORG_PREFIX}/webgrph/crawl/c-stream-sync").mock(
        return_value=mock_response({
            "crawl_id": "c-stream-sync", "status": "completed", "organization_id": TEST_ORG_ID,
            "total_pages": 1, "max_depth_reached": 0, "artifact_id": "art-stream",
            "error": None, "graph_data": None,
        })
    )
    respx.get(f"{TEST_BASE_URL}{ORG_PREFIX}/webgrph/crawl/c-stream-sync/pages").mock(
        return_value=mock_response({
            "crawl_id": "c-stream-sync",
            "nodes": [
                {"id": "n1", "url": "https://example.com", "depth": 0, "category": "page", "children_urls": [], "classification_confidence": 0.0, "metadata": {"title": "Home"}},
            ],
            "next_cursor": None, "total": 1,
        })
    )
    respx.post(f"{TEST_BASE_URL}{ORG_PREFIX}/evadr/fetch").mock(
        return_value=mock_response({
            "success": True, "url": "https://example.com", "status_code": 200,
            "tier_used": 1, "html": "<html>stream</html>", "vendor_detected": None,
            "anti_bot_bypassed": False, "artifact_id": "art-fetch", "error": None,
        })
    )
    events = list(client.crawl_stream("https://example.com", max_depth=1, poll_interval=0.01))
    types = [e.type for e in events]
    assert "discovery_started" in types
    assert "discovery_complete" in types
    assert "page_fetching" in types
    assert "page_fetched" in types
    assert "crawl_complete" in types
    final_event = events[-1]
    assert final_event.type == "crawl_complete"
    result = final_event.metadata["result"]
    assert result.pages_fetched == 1
