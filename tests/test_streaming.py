"""
Tests for SSE streaming methods.

All four streaming endpoints are tested:
    - evadr.fetch_stream()      (AsyncEvadrNamespace)
    - webgrph.crawl_stream()    (AsyncWebgrphNamespace)
    - skanyr.discover_stream()  (AsyncSkanyrNamespace)
    - parlyr.chat_stream()      (AsyncParlyrNamespace)
    - parlyr.chat()             (ParlyrNamespace — sync SSE collector)

Strategy: patch httpx.AsyncClient / httpx.Client with a mock whose
.stream() context manager yields lines via aiter_lines() / iter_lines().
This exercises every line of the SSE parsing logic without a real network.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager, contextmanager
from typing import AsyncIterator, Iterator, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from kloakd import AsyncKloakd, Kloakd
from tests.conftest import TEST_BASE_URL, TEST_ORG_ID


# ── helpers ──────────────────────────────────────────────────────────────────

def _sse_lines(*events: dict) -> List[str]:
    """Build a list of SSE data: lines from dicts."""
    lines = []
    for ev in events:
        lines.append(f"data: {json.dumps(ev)}")
        lines.append("")
    return lines


def _sse_event_lines(*pairs) -> List[str]:
    """Build event: / data: pairs for named SSE events."""
    lines = []
    for event_name, data in pairs:
        lines.append(f"event: {event_name}")
        lines.append(f"data: {json.dumps(data)}")
        lines.append("")
    return lines


class _MockStreamResponse:
    """Sync mock for httpx response inside .stream() context."""

    def __init__(self, lines: List[str], status_code: int = 200) -> None:
        self.status_code = status_code
        self._lines = lines

    def iter_lines(self) -> Iterator[str]:
        yield from self._lines

    def __enter__(self) -> "_MockStreamResponse":
        return self

    def __exit__(self, *args) -> None:
        pass


class _MockAsyncStreamResponse:
    """Async mock for httpx response inside async .stream() context."""

    def __init__(self, lines: List[str], status_code: int = 200) -> None:
        self.status_code = status_code
        self._lines = lines

    async def aiter_lines(self) -> AsyncIterator[str]:
        for line in self._lines:
            yield line

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


def _make_async_http_client(response: _MockAsyncStreamResponse) -> MagicMock:
    """
    Build a mock httpx.AsyncClient where .stream() is an async context manager
    returning the given response.
    """
    mock_client = AsyncMock()
    mock_client.stream = MagicMock(return_value=response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


def _make_sync_http_client(response: _MockStreamResponse) -> MagicMock:
    """Build a mock httpx.Client where .stream() returns a context manager yielding response."""
    @contextmanager
    def _stream_cm(*args, **kwargs):
        yield response

    mock_client = MagicMock()
    mock_client.stream = MagicMock(side_effect=_stream_cm)
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    return mock_client


@pytest.fixture
def client() -> Kloakd:
    return Kloakd(api_key="sk-test-key", organization_id=TEST_ORG_ID, base_url=TEST_BASE_URL)


@pytest.fixture
def async_client() -> AsyncKloakd:
    return AsyncKloakd(api_key="sk-test-key", organization_id=TEST_ORG_ID, base_url=TEST_BASE_URL)


# ── evadr.fetch_stream ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_evadr_fetch_stream_yields_events(async_client: AsyncKloakd) -> None:
    lines = _sse_lines(
        {"type": "tier_start", "tier": 1, "vendor": None, "metadata": {}},
        {"type": "tier_complete", "tier": 1, "vendor": "cloudflare", "metadata": {"bypassed": True}},
        {"type": "done", "tier": 1, "vendor": "cloudflare", "metadata": {}},
    )
    mock_response = _MockAsyncStreamResponse(lines)
    mock_client = _make_async_http_client(mock_response)

    with patch("httpx.AsyncClient", return_value=mock_client):
        collected = []
        async with async_client.evadr.fetch_stream("https://example.com") as events:
            async for event in events:
                collected.append(event)

    assert len(collected) == 3
    assert collected[0].type == "tier_start"
    assert collected[0].tier == 1
    assert collected[1].type == "tier_complete"
    assert collected[1].vendor == "cloudflare"
    assert collected[2].type == "done"


@pytest.mark.asyncio
async def test_evadr_fetch_stream_skips_non_data_lines(async_client: AsyncKloakd) -> None:
    lines = [
        ": keep-alive",
        "",
        'data: {"type": "tier_start", "tier": 2, "vendor": null, "metadata": {}}',
        "",
        "comment: ignored",
        'data: {"type": "done", "tier": 2, "vendor": null, "metadata": {}}',
    ]
    mock_response = _MockAsyncStreamResponse(lines)
    mock_client = _make_async_http_client(mock_response)

    with patch("httpx.AsyncClient", return_value=mock_client):
        collected = []
        async with async_client.evadr.fetch_stream("https://example.com", force_browser=True) as events:
            async for event in events:
                collected.append(event)

    assert len(collected) == 2
    assert collected[0].tier == 2


@pytest.mark.asyncio
async def test_evadr_fetch_stream_skips_malformed_json(async_client: AsyncKloakd) -> None:
    lines = [
        "data: {not valid json",
        "data: {}",
        'data: {"type": "ok", "tier": 1, "vendor": null, "metadata": {}}',
    ]
    mock_response = _MockAsyncStreamResponse(lines)
    mock_client = _make_async_http_client(mock_response)

    with patch("httpx.AsyncClient", return_value=mock_client):
        collected = []
        async with async_client.evadr.fetch_stream("https://example.com") as events:
            async for event in events:
                collected.append(event)

    # malformed JSON skipped; empty data {} yields FetchEvent with empty type
    assert collected[-1].type == "ok"


# ── webgrph.crawl_stream ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_webgrph_crawl_stream_yields_events(async_client: AsyncKloakd) -> None:
    lines = _sse_lines(
        {"type": "page_found", "url": "https://example.com", "depth": 0, "pages_found": 1, "metadata": {}},
        {"type": "page_found", "url": "https://example.com/about", "depth": 1, "pages_found": 2, "metadata": {}},
        {"type": "done", "url": None, "depth": None, "pages_found": 2, "metadata": {}},
    )
    mock_response = _MockAsyncStreamResponse(lines)
    mock_client = _make_async_http_client(mock_response)

    with patch("httpx.AsyncClient", return_value=mock_client):
        collected = []
        async with async_client.webgrph.crawl_stream("https://example.com") as events:
            async for event in events:
                collected.append(event)

    assert len(collected) == 3
    assert collected[0].type == "page_found"
    assert collected[0].url == "https://example.com"
    assert collected[0].depth == 0
    assert collected[0].pages_found == 1
    assert collected[1].url == "https://example.com/about"
    assert collected[2].type == "done"


@pytest.mark.asyncio
async def test_webgrph_crawl_stream_with_params(async_client: AsyncKloakd) -> None:
    lines = _sse_lines(
        {"type": "page_found", "url": "https://ex.com", "depth": 0, "pages_found": 1, "metadata": {}},
    )
    mock_response = _MockAsyncStreamResponse(lines)
    mock_client = _make_async_http_client(mock_response)

    with patch("httpx.AsyncClient", return_value=mock_client):
        collected = []
        async with async_client.webgrph.crawl_stream(
            "https://ex.com", max_depth=5, max_pages=200
        ) as events:
            async for event in events:
                collected.append(event)

    assert len(collected) == 1
    # Verify stream method was called with correct payload
    call_kwargs = mock_client.stream.call_args
    assert call_kwargs[1]["json"]["max_depth"] == 5
    assert call_kwargs[1]["json"]["max_pages"] == 200


@pytest.mark.asyncio
async def test_webgrph_crawl_stream_skips_malformed_json(async_client: AsyncKloakd) -> None:
    lines = [
        "data: BROKEN",
        'data: {"type": "page_found", "url": "https://x.com", "depth": 0, "pages_found": 1, "metadata": {}}',
    ]
    mock_response = _MockAsyncStreamResponse(lines)
    mock_client = _make_async_http_client(mock_response)

    with patch("httpx.AsyncClient", return_value=mock_client):
        collected = []
        async with async_client.webgrph.crawl_stream("https://x.com") as events:
            async for event in events:
                collected.append(event)

    assert len(collected) == 1
    assert collected[0].url == "https://x.com"


# ── skanyr.discover_stream ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_skanyr_discover_stream_yields_events(async_client: AsyncKloakd) -> None:
    lines = _sse_lines(
        {"type": "endpoint_found", "endpoint_url": "https://api.example.com/v1/products", "api_type": "rest", "metadata": {"method": "GET"}},
        {"type": "endpoint_found", "endpoint_url": "https://api.example.com/graphql", "api_type": "graphql", "metadata": {}},
        {"type": "done", "endpoint_url": None, "api_type": None, "metadata": {}},
    )
    mock_response = _MockAsyncStreamResponse(lines)
    mock_client = _make_async_http_client(mock_response)

    with patch("httpx.AsyncClient", return_value=mock_client):
        collected = []
        async with async_client.skanyr.discover_stream("https://api.example.com") as events:
            async for event in events:
                collected.append(event)

    assert len(collected) == 3
    assert collected[0].type == "endpoint_found"
    assert collected[0].endpoint_url == "https://api.example.com/v1/products"
    assert collected[0].api_type == "rest"
    assert collected[1].api_type == "graphql"
    assert collected[2].type == "done"


@pytest.mark.asyncio
async def test_skanyr_discover_stream_with_hierarchy_artifact(async_client: AsyncKloakd) -> None:
    lines = _sse_lines(
        {"type": "done", "endpoint_url": None, "api_type": None, "metadata": {}},
    )
    mock_response = _MockAsyncStreamResponse(lines)
    mock_client = _make_async_http_client(mock_response)

    with patch("httpx.AsyncClient", return_value=mock_client):
        async with async_client.skanyr.discover_stream(
            "https://api.example.com",
            site_hierarchy_artifact_id="art-hier-001",
        ) as events:
            async for _ in events:
                pass

    call_kwargs = mock_client.stream.call_args
    assert call_kwargs[1]["json"]["site_hierarchy_artifact_id"] == "art-hier-001"


@pytest.mark.asyncio
async def test_skanyr_discover_stream_skips_non_data_lines(async_client: AsyncKloakd) -> None:
    lines = [
        ": heartbeat",
        "",
        'data: {"type": "endpoint_found", "endpoint_url": "https://api.x.com/ep", "api_type": "rest", "metadata": {}}',
        "",
    ]
    mock_response = _MockAsyncStreamResponse(lines)
    mock_client = _make_async_http_client(mock_response)

    with patch("httpx.AsyncClient", return_value=mock_client):
        collected = []
        async with async_client.skanyr.discover_stream("https://api.x.com") as events:
            async for event in events:
                collected.append(event)

    assert len(collected) == 1


# ── parlyr.chat_stream (async) ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_parlyr_chat_stream_yields_events(async_client: AsyncKloakd) -> None:
    lines = _sse_event_lines(
        ("intent", {"intent": "scrape_products", "confidence": 0.95, "tier": 1, "entities": {}, "requires_action": False}),
        ("response", {"content": "I'll scrape products from example.com for you."}),
        ("done", {}),
    )
    mock_response = _MockAsyncStreamResponse(lines)
    mock_client = _make_async_http_client(mock_response)

    with patch("httpx.AsyncClient", return_value=mock_client):
        collected = []
        async with async_client.parlyr.chat_stream("sess-001", "Scrape example.com") as events:
            async for event in events:
                collected.append(event)

    assert len(collected) == 3
    assert collected[0].event == "intent"
    assert collected[0].data["intent"] == "scrape_products"
    assert collected[1].event == "response"
    assert "example.com" in collected[1].data["content"]
    assert collected[2].event == "done"


@pytest.mark.asyncio
async def test_parlyr_chat_stream_skips_malformed_json(async_client: AsyncKloakd) -> None:
    lines = [
        "event: intent",
        "data: NOT_JSON",
        "",
        "event: response",
        'data: {"content": "OK"}',
        "",
    ]
    mock_response = _MockAsyncStreamResponse(lines)
    mock_client = _make_async_http_client(mock_response)

    with patch("httpx.AsyncClient", return_value=mock_client):
        collected = []
        async with async_client.parlyr.chat_stream("sess-002", "hello") as events:
            async for event in events:
                collected.append(event)

    # malformed JSON line skipped
    assert len(collected) == 1
    assert collected[0].event == "response"


@pytest.mark.asyncio
async def test_parlyr_chat_stream_session_id_in_payload(async_client: AsyncKloakd) -> None:
    lines = _sse_event_lines(("done", {}))
    mock_response = _MockAsyncStreamResponse(lines)
    mock_client = _make_async_http_client(mock_response)

    with patch("httpx.AsyncClient", return_value=mock_client):
        async with async_client.parlyr.chat_stream("my-session", "hello") as events:
            async for _ in events:
                pass

    call_kwargs = mock_client.stream.call_args
    assert call_kwargs[1]["json"]["session_id"] == "my-session"
    assert call_kwargs[1]["json"]["message"] == "hello"


# ── parlyr.chat (sync SSE collector) ─────────────────────────────────────────

def test_parlyr_chat_collects_full_turn(client: Kloakd) -> None:
    lines = _sse_event_lines(
        ("intent", {"intent": "scrape_products", "confidence": 0.92, "tier": 1, "entities": {"url": "https://example.com"}, "requires_action": False}),
        ("response", {"content": "I'll extract all product prices from example.com."}),
        ("done", {}),
    )
    mock_response = _MockStreamResponse(lines)
    mock_client = _make_sync_http_client(mock_response)

    with patch("httpx.Client", return_value=mock_client):
        result = client.parlyr.chat("sess-001", "Get all prices from example.com")

    assert result.session_id == "sess-001"
    assert result.intent == "scrape_products"
    assert result.confidence == 0.92
    assert result.tier == 1
    assert "example.com" in result.response
    assert result.requires_action is False


def test_parlyr_chat_handles_missing_intent_event(client: Kloakd) -> None:
    """If no intent event arrives, ChatTurn uses safe defaults."""
    lines = _sse_event_lines(
        ("response", {"content": "Here you go."}),
        ("done", {}),
    )
    mock_response = _MockStreamResponse(lines)
    mock_client = _make_sync_http_client(mock_response)

    with patch("httpx.Client", return_value=mock_client):
        result = client.parlyr.chat("sess-002", "hello")

    assert result.intent == "unknown"
    assert result.confidence == 0.0
    assert result.response == "Here you go."


def test_parlyr_chat_skips_malformed_json(client: Kloakd) -> None:
    lines = [
        "event: intent",
        "data: BROKEN",
        "",
        "event: response",
        '  data: {"content": "Done."}',
        "",
    ]
    mock_response = _MockStreamResponse(lines)
    mock_client = _make_sync_http_client(mock_response)

    with patch("httpx.Client", return_value=mock_client):
        result = client.parlyr.chat("sess-003", "hi")

    assert result.intent == "unknown"


def test_parlyr_chat_payload_contains_session_and_message(client: Kloakd) -> None:
    lines = _sse_event_lines(("done", {}))
    mock_response = _MockStreamResponse(lines)
    mock_client = _make_sync_http_client(mock_response)

    with patch("httpx.Client", return_value=mock_client):
        client.parlyr.chat("sess-abc", "my message")

    call_kwargs = mock_client.stream.call_args
    assert call_kwargs[1]["json"]["session_id"] == "sess-abc"
    assert call_kwargs[1]["json"]["message"] == "my message"
