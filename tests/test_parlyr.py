"""Tests for the Parlyr namespace."""

from __future__ import annotations

import pytest
import respx
from httpx import Response

from kloakd import Kloakd, ParseResult
from tests.conftest import TEST_BASE_URL, TEST_ORG_ID, ORG_PREFIX, mock_response


@pytest.fixture
def client() -> Kloakd:
    return Kloakd(api_key="sk-test-key", organization_id=TEST_ORG_ID, base_url=TEST_BASE_URL)


@respx.mock
def test_parse_success(client: Kloakd) -> None:
    respx.post(f"{TEST_BASE_URL}{ORG_PREFIX}/parlyr/parse").mock(
        return_value=mock_response({
            "intent": "scrape_products",
            "confidence": 0.94,
            "tier": 1,
            "source": "pattern_match",
            "entities": {"url": "https://example.com", "fields": ["title", "price"]},
            "requires_action": False,
            "clarification_needed": None,
            "reasoning": None,
            "detected_url": "https://example.com",
        })
    )
    result = client.parlyr.parse("Get all product names and prices from example.com")
    assert isinstance(result, ParseResult)
    assert result.intent == "scrape_products"
    assert result.confidence == 0.94
    assert result.tier == 1
    assert result.detected_url == "https://example.com"
    assert result.ok is True


@respx.mock
def test_parse_requires_clarification(client: Kloakd) -> None:
    respx.post(f"{TEST_BASE_URL}{ORG_PREFIX}/parlyr/parse").mock(
        return_value=mock_response({
            "intent": "unknown",
            "confidence": 0.30,
            "tier": 3,
            "source": "llm",
            "entities": {},
            "requires_action": True,
            "clarification_needed": "Which URL should I scrape?",
            "reasoning": "No URL detected in message",
            "detected_url": None,
        })
    )
    result = client.parlyr.parse("Get me some stuff")
    assert result.requires_action is True
    assert result.clarification_needed == "Which URL should I scrape?"
    assert result.ok is False


@respx.mock
def test_parse_with_session_id(client: Kloakd) -> None:
    route = respx.post(f"{TEST_BASE_URL}{ORG_PREFIX}/parlyr/parse")
    route.mock(return_value=mock_response({
        "intent": "scrape_products",
        "confidence": 0.88,
        "tier": 1,
        "source": "session_context",
        "entities": {},
        "requires_action": False,
        "clarification_needed": None,
        "reasoning": None,
        "detected_url": None,
    }))
    client.parlyr.parse("Get the prices too", session_id="sess-001")
    import json
    sent = json.loads(route.calls[0].request.content)
    assert sent["session_id"] == "sess-001"


@respx.mock
def test_delete_session(client: Kloakd) -> None:
    respx.delete(f"{TEST_BASE_URL}{ORG_PREFIX}/parlyr/chat/sess-001").mock(
        return_value=Response(204)
    )
    client.parlyr.delete_session("sess-001")


@respx.mock
def test_parse_high_confidence_tier1(client: Kloakd) -> None:
    respx.post(f"{TEST_BASE_URL}{ORG_PREFIX}/parlyr/parse").mock(
        return_value=mock_response({
            "intent": "scrape_table",
            "confidence": 0.99,
            "tier": 1,
            "source": "exact_pattern",
            "entities": {"url": "https://data.example.com/table"},
            "requires_action": False,
            "clarification_needed": None,
            "reasoning": None,
            "detected_url": "https://data.example.com/table",
        })
    )
    result = client.parlyr.parse("Scrape the table at data.example.com/table")
    assert result.tier == 1
    assert result.confidence == 0.99
    assert result.source == "exact_pattern"
