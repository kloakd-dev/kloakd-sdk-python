"""Tests for the Kolektr namespace."""

from __future__ import annotations

import pytest
import respx

from kloakd import ExtractionResult, Kloakd
from tests.conftest import TEST_BASE_URL, TEST_ORG_ID, ORG_PREFIX, mock_response


@pytest.fixture
def client() -> Kloakd:
    return Kloakd(api_key="sk-test-key", organization_id=TEST_ORG_ID, base_url=TEST_BASE_URL)


@respx.mock
def test_page_simple(client: Kloakd) -> None:
    respx.post(f"{TEST_BASE_URL}{ORG_PREFIX}/kolektr/extract").mock(
        return_value=mock_response({
            "success": True,
            "url": "https://books.toscrape.com",
            "method": "l1_css",
            "records": [
                {"title": "A Light in the Attic", "price": "£51.77"},
                {"title": "Tipping the Velvet", "price": "£53.74"},
            ],
            "total_records": 2,
            "pages_scraped": 1,
            "artifact_id": "art-kolektr-001",
            "job_id": None,
            "has_more": False,
            "total": 2,
            "error": None,
        })
    )
    result = client.kolektr.page(
        "https://books.toscrape.com",
        schema={"title": "css:h3 a", "price": "css:p.price_color"},
    )
    assert isinstance(result, ExtractionResult)
    assert result.success is True
    assert result.total_records == 2
    assert result.method == "l1_css"
    assert result.records[0]["title"] == "A Light in the Attic"
    assert result.artifact_id == "art-kolektr-001"
    assert result.ok is True


@respx.mock
def test_page_with_fetch_artifact(client: Kloakd) -> None:
    route = respx.post(f"{TEST_BASE_URL}{ORG_PREFIX}/kolektr/extract")
    route.mock(return_value=mock_response({
        "success": True,
        "url": "https://example.com",
        "method": "l1_css",
        "records": [{"name": "Widget"}],
        "total_records": 1,
        "pages_scraped": 1,
        "artifact_id": "art-002",
        "error": None,
    }))
    result = client.kolektr.page(
        "https://example.com",
        fetch_artifact_id="art-evadr-001",
    )
    assert result.ok is True
    assert route.called
    sent_body = route.calls[0].request.content
    import json
    body = json.loads(sent_body)
    assert body["fetch_artifact_id"] == "art-evadr-001"


@respx.mock
def test_extract_html(client: Kloakd) -> None:
    respx.post(f"{TEST_BASE_URL}{ORG_PREFIX}/kolektr/extract/html").mock(
        return_value=mock_response({
            "success": True,
            "url": "https://example.com",
            "method": "in_process_html",
            "records": [{"price": "$9.99"}],
            "total_records": 1,
            "pages_scraped": 0,
            "artifact_id": None,
            "error": None,
        })
    )
    result = client.kolektr.extract_html(
        html="<html><span class='price'>$9.99</span></html>",
        url="https://example.com",
        schema={"price": "css:span.price"},
    )
    assert result.success is True
    assert result.method == "in_process_html"
    assert result.records[0]["price"] == "$9.99"


@respx.mock
def test_page_pagination(client: Kloakd) -> None:
    call_count = 0

    def paginate_side_effect(request, **kwargs):
        nonlocal call_count
        call_count += 1
        import json as _json
        body = _json.loads(request.content)
        offset = body.get("offset", 0)
        if offset == 0:
            return mock_response({
                "success": True, "url": "https://ex.com", "method": "l1_css",
                "records": [{"i": 1}], "total_records": 1,
                "pages_scraped": 1, "artifact_id": None, "error": None,
                "has_more": True, "total": 2,
            })
        return mock_response({
            "success": True, "url": "https://ex.com", "method": "l1_css",
            "records": [{"i": 2}], "total_records": 1,
            "pages_scraped": 1, "artifact_id": None, "error": None,
            "has_more": False, "total": 2,
        })

    respx.post(f"{TEST_BASE_URL}{ORG_PREFIX}/kolektr/extract").mock(
        side_effect=paginate_side_effect
    )
    all_records = client.kolektr.page_all("https://ex.com")
    assert len(all_records) == 2
    assert call_count == 2
