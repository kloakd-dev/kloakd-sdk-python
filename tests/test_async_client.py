"""Tests for AsyncKloakd — verifies async namespace methods mirror sync behaviour."""

from __future__ import annotations

import pytest
import respx

from kloakd import (
    AsyncKloakd,
    DiscoverResult,
    ExtractionResult,
    FetchResult,
    NexusAnalyzeResult,
    ParseResult,
    SessionResult,
)
from tests.conftest import TEST_BASE_URL, TEST_ORG_ID, ORG_PREFIX, mock_response


@pytest.fixture
def async_client() -> AsyncKloakd:
    return AsyncKloakd(
        api_key="sk-test-key",
        organization_id=TEST_ORG_ID,
        base_url=TEST_BASE_URL,
    )


class TestAsyncClientValidation:
    def test_empty_api_key_raises(self) -> None:
        with pytest.raises(ValueError, match="api_key"):
            AsyncKloakd(api_key="", organization_id=TEST_ORG_ID)

    def test_empty_org_id_raises(self) -> None:
        with pytest.raises(ValueError, match="organization_id"):
            AsyncKloakd(api_key="sk-test-key", organization_id="")

    def test_repr(self) -> None:
        client = AsyncKloakd(api_key="sk-test-key", organization_id=TEST_ORG_ID)
        assert "AsyncKloakd" in repr(client)
        assert TEST_ORG_ID in repr(client)


@respx.mock
@pytest.mark.asyncio
async def test_async_evadr_fetch(async_client: AsyncKloakd) -> None:
    respx.post(f"{TEST_BASE_URL}{ORG_PREFIX}/evadr/fetch").mock(
        return_value=mock_response({
            "success": True,
            "url": "https://example.com",
            "status_code": 200,
            "tier_used": 2,
            "html": "<html>async</html>",
            "vendor_detected": None,
            "anti_bot_bypassed": False,
            "artifact_id": "art-async-001",
            "error": None,
        })
    )
    result = await async_client.evadr.fetch("https://example.com")
    assert isinstance(result, FetchResult)
    assert result.tier_used == 2
    assert result.artifact_id == "art-async-001"
    assert result.ok is True


@respx.mock
@pytest.mark.asyncio
async def test_async_kolektr_page(async_client: AsyncKloakd) -> None:
    respx.post(f"{TEST_BASE_URL}{ORG_PREFIX}/kolektr/extract").mock(
        return_value=mock_response({
            "success": True,
            "url": "https://example.com",
            "method": "l1_css",
            "records": [{"title": "Async Book"}],
            "total_records": 1,
            "pages_scraped": 1,
            "artifact_id": None,
            "error": None,
        })
    )
    result = await async_client.kolektr.page(
        "https://example.com",
        schema={"title": "css:h3 a"},
    )
    assert isinstance(result, ExtractionResult)
    assert result.records[0]["title"] == "Async Book"


@respx.mock
@pytest.mark.asyncio
async def test_async_webgrph_crawl(async_client: AsyncKloakd) -> None:
    respx.post(f"{TEST_BASE_URL}{ORG_PREFIX}/webgrph/crawl").mock(
        return_value=mock_response({
            "success": True,
            "crawl_id": "c-async-001",
            "url": "https://example.com",
            "total_pages": 1,
            "max_depth_reached": 0,
            "pages": [{"url": "https://example.com", "depth": 0, "title": "Home", "status_code": 200, "children": []}],
            "artifact_id": "art-hier-async",
            "has_more": False,
            "total": 1,
            "error": None,
        })
    )
    result = await async_client.webgrph.crawl("https://example.com")
    assert result.crawl_id == "c-async-001"
    assert result.ok is True


@respx.mock
@pytest.mark.asyncio
async def test_async_skanyr_discover(async_client: AsyncKloakd) -> None:
    respx.post(f"{TEST_BASE_URL}{ORG_PREFIX}/skanyr/discover").mock(
        return_value=mock_response({
            "success": True,
            "discovery_id": "d-async-001",
            "url": "https://api.example.com",
            "total_endpoints": 1,
            "endpoints": [{"url": "https://api.example.com/v1", "method": "GET", "api_type": "rest", "confidence": 0.9, "parameters": {}}],
            "artifact_id": "art-map-async",
            "has_more": False,
            "total": 1,
            "error": None,
        })
    )
    result = await async_client.skanyr.discover("https://api.example.com")
    assert isinstance(result, DiscoverResult)
    assert result.total_endpoints == 1


@respx.mock
@pytest.mark.asyncio
async def test_async_nexus_analyze(async_client: AsyncKloakd) -> None:
    respx.post(f"{TEST_BASE_URL}{ORG_PREFIX}/nexus/analyze").mock(
        return_value=mock_response({
            "perception_id": "perc-async-001",
            "strategy": {},
            "page_type": "listing",
            "complexity_level": "low",
            "artifact_id": None,
            "duration_ms": 100,
            "error": None,
        })
    )
    result = await async_client.nexus.analyze("https://example.com")
    assert isinstance(result, NexusAnalyzeResult)
    assert result.perception_id == "perc-async-001"


@respx.mock
@pytest.mark.asyncio
async def test_async_parlyr_parse(async_client: AsyncKloakd) -> None:
    respx.post(f"{TEST_BASE_URL}{ORG_PREFIX}/parlyr/parse").mock(
        return_value=mock_response({
            "intent": "scrape_products",
            "confidence": 0.91,
            "tier": 1,
            "source": "pattern_match",
            "entities": {},
            "requires_action": False,
            "clarification_needed": None,
            "reasoning": None,
            "detected_url": "https://example.com",
        })
    )
    result = await async_client.parlyr.parse("Scrape example.com")
    assert isinstance(result, ParseResult)
    assert result.intent == "scrape_products"


@respx.mock
@pytest.mark.asyncio
async def test_async_fetchyr_login(async_client: AsyncKloakd) -> None:
    respx.post(f"{TEST_BASE_URL}{ORG_PREFIX}/fetchyr/login").mock(
        return_value=mock_response({
            "success": True,
            "session_id": "sess-async-001",
            "url": "https://app.example.com/dashboard",
            "artifact_id": "art-sess-async",
            "screenshot_url": None,
            "error": None,
        })
    )
    result = await async_client.fetchyr.login(
        url="https://app.example.com/login",
        username_selector="#email",
        password_selector="#password",
        username="user@example.com",
        password="s3cr3t",
    )
    assert isinstance(result, SessionResult)
    assert result.artifact_id == "art-sess-async"


@respx.mock
@pytest.mark.asyncio
async def test_async_fetchyr_detect_mfa(async_client: AsyncKloakd) -> None:
    respx.post(f"{TEST_BASE_URL}{ORG_PREFIX}/fetchyr/detect-mfa").mock(
        return_value=mock_response({
            "mfa_detected": True,
            "challenge_id": "ch-async-001",
            "mfa_type": "sms",
            "error": None,
        })
    )
    result = await async_client.fetchyr.detect_mfa("https://app.example.com/mfa")
    assert result.mfa_detected is True
    assert result.mfa_type == "sms"


@respx.mock
@pytest.mark.asyncio
async def test_async_fetchyr_check_duplicates(async_client: AsyncKloakd) -> None:
    records = [{"title": "A"}, {"title": "A"}, {"title": "B"}]
    respx.post(f"{TEST_BASE_URL}{ORG_PREFIX}/fetchyr/deduplicate").mock(
        return_value=mock_response({
            "unique_records": [{"title": "A"}, {"title": "B"}],
            "duplicate_count": 1,
            "total_input": 3,
            "error": None,
        })
    )
    result = await async_client.fetchyr.check_duplicates(records)
    assert result.duplicate_count == 1
    assert len(result.unique_records) == 2


@respx.mock
@pytest.mark.asyncio
async def test_async_kolektr_extract_html(async_client: AsyncKloakd) -> None:
    respx.post(f"{TEST_BASE_URL}{ORG_PREFIX}/kolektr/extract/html").mock(
        return_value=mock_response({
            "success": True,
            "url": "https://example.com",
            "method": "in_process_html",
            "records": [{"price": "$5.00"}],
            "total_records": 1,
            "pages_scraped": 0,
            "artifact_id": None,
            "error": None,
        })
    )
    result = await async_client.kolektr.extract_html(
        "<html><span class='price'>$5.00</span></html>",
        "https://example.com",
    )
    assert result.ok is True
    assert result.records[0]["price"] == "$5.00"
