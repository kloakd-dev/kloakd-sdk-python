"""Tests for the Evadr namespace."""

from __future__ import annotations

import pytest
import respx
from httpx import Response

from kloakd import AnalyzeResult, AuthenticationError, FetchResult, Kloakd, RateLimitError
from tests.conftest import TEST_BASE_URL, TEST_ORG_ID, ORG_PREFIX, mock_response, error_response


@pytest.fixture
def client() -> Kloakd:
    from kloakd import Kloakd
    return Kloakd(api_key="sk-test-key", organization_id=TEST_ORG_ID, base_url=TEST_BASE_URL)


@respx.mock
def test_fetch_success(client: Kloakd) -> None:
    respx.post(f"{TEST_BASE_URL}{ORG_PREFIX}/evadr/fetch").mock(
        return_value=mock_response({
            "success": True,
            "url": "https://example.com",
            "status_code": 200,
            "tier_used": 1,
            "html": "<html>...</html>",
            "vendor_detected": None,
            "anti_bot_bypassed": False,
            "artifact_id": "art-abc123",
            "error": None,
        })
    )
    result = client.evadr.fetch("https://example.com")
    assert isinstance(result, FetchResult)
    assert result.success is True
    assert result.tier_used == 1
    assert result.artifact_id == "art-abc123"
    assert result.ok is True


@respx.mock
def test_fetch_with_bypass(client: Kloakd) -> None:
    respx.post(f"{TEST_BASE_URL}{ORG_PREFIX}/evadr/fetch").mock(
        return_value=mock_response({
            "success": True,
            "url": "https://protected.com",
            "status_code": 200,
            "tier_used": 3,
            "html": "<html>...</html>",
            "vendor_detected": "cloudflare",
            "anti_bot_bypassed": True,
            "artifact_id": "art-xyz789",
            "error": None,
        })
    )
    result = client.evadr.fetch("https://protected.com", force_browser=True, use_proxy=True)
    assert result.tier_used == 3
    assert result.vendor_detected == "cloudflare"
    assert result.anti_bot_bypassed is True


@respx.mock
def test_fetch_raises_auth_error(client: Kloakd) -> None:
    respx.post(f"{TEST_BASE_URL}{ORG_PREFIX}/evadr/fetch").mock(
        return_value=error_response(401, "Invalid API key")
    )
    with pytest.raises(AuthenticationError) as exc_info:
        client.evadr.fetch("https://example.com")
    assert exc_info.value.status_code == 401


@respx.mock
def test_fetch_raises_rate_limit(client: Kloakd) -> None:
    respx.post(f"{TEST_BASE_URL}{ORG_PREFIX}/evadr/fetch").mock(
        return_value=Response(429, json={"detail": "Too many requests", "retry_after": 30})
    )
    with pytest.raises(RateLimitError) as exc_info:
        client.evadr.fetch("https://example.com")
    assert exc_info.value.status_code == 429
    assert exc_info.value.retry_after == 30


@respx.mock
def test_analyze_success(client: Kloakd) -> None:
    respx.post(f"{TEST_BASE_URL}{ORG_PREFIX}/evadr/analyze").mock(
        return_value=mock_response({
            "blocked": True,
            "vendor": "datadome",
            "confidence": 0.97,
            "recommended_actions": ["use_proxy", "rotate_fingerprint"],
        })
    )
    result = client.evadr.analyze(
        "https://example.com",
        status_code=403,
        body_snippet="Your access has been blocked",
    )
    assert isinstance(result, AnalyzeResult)
    assert result.blocked is True
    assert result.vendor == "datadome"
    assert result.confidence == 0.97
    assert len(result.recommended_actions) == 2


@respx.mock
def test_store_proxy(client: Kloakd) -> None:
    respx.post(f"{TEST_BASE_URL}{ORG_PREFIX}/evadr/proxies").mock(
        return_value=mock_response({"ok": True})
    )
    client.evadr.store_proxy("residential-us", "http://user:pass@proxy.example.com:8080")


@respx.mock
def test_fetch_error_field_propagates(client: Kloakd) -> None:
    respx.post(f"{TEST_BASE_URL}{ORG_PREFIX}/evadr/fetch").mock(
        return_value=mock_response({
            "success": False,
            "url": "https://example.com",
            "status_code": 0,
            "tier_used": 5,
            "html": None,
            "vendor_detected": None,
            "anti_bot_bypassed": False,
            "artifact_id": None,
            "error": "All tiers exhausted",
        })
    )
    result = client.evadr.fetch("https://example.com")
    assert result.success is False
    assert result.ok is False
    assert result.error == "All tiers exhausted"
