"""Tests for the Webgrph namespace."""

from __future__ import annotations

import pytest
import respx

from kloakd import CrawlResult, Kloakd, PageNode
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
            "total_pages": 2,
            "max_depth_reached": 1,
            "pages": [
                {"url": "https://example.com", "depth": 0, "title": "Home", "status_code": 200, "children": []},
                {"url": "https://example.com/about", "depth": 1, "title": "About", "status_code": 200, "children": []},
            ],
            "artifact_id": "art-hierarchy-001",
            "has_more": False,
            "total": 2,
            "error": None,
        })
    )
    result = client.webgrph.crawl("https://example.com", max_depth=2)
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
    call_count = 0

    def paginate(request, **kwargs):
        nonlocal call_count
        call_count += 1
        import json as _j
        offset = _j.loads(request.content).get("offset", 0)
        page = {"url": f"https://ex.com/page{offset}", "depth": 0, "title": f"Page {offset}", "status_code": 200, "children": []}
        return mock_response({
            "success": True, "crawl_id": "c1", "url": "https://ex.com",
            "total_pages": 2, "max_depth_reached": 0, "pages": [page],
            "artifact_id": None, "has_more": offset == 0, "total": 2, "error": None,
        })

    respx.post(f"{TEST_BASE_URL}{ORG_PREFIX}/webgrph/crawl").mock(side_effect=paginate)
    pages = client.webgrph.crawl_all("https://ex.com")
    assert len(pages) == 2
    assert call_count == 2
