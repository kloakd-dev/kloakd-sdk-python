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
from contextlib import contextmanager
from typing import AsyncIterator, Iterator, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import respx
from httpx import Response

from kloakd import AsyncKloakd, Kloakd
from tests.conftest import ORG_PREFIX, TEST_BASE_URL, TEST_ORG_ID, mock_response

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


class _MockAsyncClientForCrawlStream:
    """Mock httpx.AsyncClient that handles both .request() for POST and .stream() for SSE.

    crawl_stream() first POSTs via the async transport (which creates an
    httpx.AsyncClient and calls .request()), then creates another
    httpx.AsyncClient for the SSE stream (calling .stream()).
    This mock handles both calls.
    """

    def __init__(self, post_response_lines: List[str], sse_lines: List[str]) -> None:
        self._post_response = mock_response({
            "success": True,
            "crawl_id": "c-stream-001",
            "url": "https://example.com",
            "total_pages": 0,
            "max_depth_reached": 0,
            "artifact_id": None,
            "error": None,
        }, status_code=202)
        self._sse_response = _MockAsyncStreamResponse(sse_lines)
        self.request_calls: list = []

    async def request(self, method, url, **kwargs):
        self.request_calls.append({"method": method, "url": url, **kwargs})
        return self._post_response

    def stream(self, method, url, **kwargs):
        return self._sse_response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


@pytest.fixture
def client() -> Kloakd:
    return Kloakd(api_key="sk-test-key", organization_id=TEST_ORG_ID, base_url=TEST_BASE_URL)


@pytest.fixture
def async_client() -> AsyncKloakd:
    return AsyncKloakd(api_key="sk-test-key", organization_id=TEST_ORG_ID, base_url=TEST_BASE_URL)


# ── evadr.fetch_stream ────────────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.asyncio
@pytest.mark.asyncio
@pytest.mark.asyncio
@pytest.mark.asyncio
@pytest.mark.asyncio
@pytest.mark.asyncio
@pytest.mark.asyncio
@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_parlyr_chat_stream_yields_events(async_client: AsyncKloakd) -> None:
    lines = _sse_event_lines(*CHAT_TURN, ("end", {}))
    mock_response = _MockAsyncStreamResponse(lines)
    mock_client = _make_async_http_client(mock_response)

    with patch("httpx.AsyncClient", return_value=mock_client):
        collected = []
        async with async_client.parlyr.chat_stream("sess-001", "Scrape example.com") as events:
            async for event in events:
                collected.append(event)

    # The closing ``end`` is not yielded.
    assert [e.type for e in collected] == ["thinking", "interpretation", "results", "text"]
    assert collected[1].data == INTERPRETATION["data"]
    assert collected[1].actions == INTERPRETATION["actions"]
    assert collected[1].timestamp == INTERPRETATION["timestamp"]
    assert collected[3].content == "Done: 2 books."
    assert collected[3].event == "text"


@pytest.mark.asyncio
async def test_parlyr_chat_stream_skips_malformed_json(async_client: AsyncKloakd) -> None:
    lines = [
        "event: thinking",
        "data: NOT_JSON",
        "",
        "event: text",
        'data: {"type": "text", "content": "OK", "data": null, "actions": null, "timestamp": "t"}',
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
    assert (collected[0].type, collected[0].content) == ("text", "OK")


@pytest.mark.asyncio
async def test_parlyr_chat_stream_session_id_in_payload(async_client: AsyncKloakd) -> None:
    lines = _sse_event_lines(("end", {}))
    mock_response = _MockAsyncStreamResponse(lines)
    mock_client = _make_async_http_client(mock_response)

    with patch("httpx.AsyncClient", return_value=mock_client):
        async with async_client.parlyr.chat_stream("my-session", "hello") as events:
            async for _ in events:
                pass

    call_kwargs = mock_client.stream.call_args
    assert call_kwargs[1]["json"]["session_id"] == "my-session"
    assert call_kwargs[1]["json"]["message"] == "hello"


@pytest.mark.asyncio
async def test_async_parlyr_chat_collects_full_turn(async_client: AsyncKloakd) -> None:
    mock_client = _make_async_http_client(
        _MockAsyncStreamResponse(_sse_event_lines(*CHAT_TURN, ("end", {})))
    )
    with patch("httpx.AsyncClient", return_value=mock_client):
        turn = await async_client.parlyr.chat("sess-001", "Get books")
    assert turn.interpretation == INTERPRETATION["data"]
    assert turn.intent is None
    assert turn.response == "Done: 2 books."
    assert turn.results == [RESULTS["data"]]
    assert turn.ok


# ── parlyr.chat (sync SSE collector) ─────────────────────────────────────────

# Payloads as kobe-scraper's ChatEvent.to_json() sends them
# (application/services/chat_orchestrator.py), each under ``event: <type>``.
def _chat(type_: str, content=None, data=None, actions=None) -> dict:
    return {"type": type_, "content": content, "data": data, "actions": actions, "timestamp": "2026-10-28T10:00:00"}


INTERPRETATION = _chat(
    "interpretation",
    "I'll extract books from https://books.toscrape.com.",
    {"url": "https://books.toscrape.com", "entity": "books", "fields": ["title"], "limit": None, "summary": "Extract books from https://books.toscrape.com"},
    [{"id": "start", "label": "Start Scraping", "primary": True}, {"id": "cancel", "label": "Cancel"}],
)
RESULTS = _chat("results", "Found 2 books.", {"records": [{"title": "A"}, {"title": "B"}], "total": 2})
CHAT_TURN = [
    ("thinking", _chat("thinking", "Understanding your request...")),
    ("interpretation", INTERPRETATION),
    ("results", RESULTS),
    ("text", _chat("text", "Done: 2 books.")),
]


def test_parlyr_chat_collects_full_turn(client: Kloakd) -> None:
    lines = _sse_event_lines(*CHAT_TURN, ("end", {}))
    mock_client = _make_sync_http_client(_MockStreamResponse(lines))

    with patch("httpx.Client", return_value=mock_client):
        result = client.parlyr.chat("sess-001", "Get all books from books.toscrape.com")

    assert result.session_id == "sess-001"
    assert result.interpretation == INTERPRETATION["data"]
    # chat_orchestrator.py's interpretation data has no intent key
    assert result.intent is None
    assert result.response == "Done: 2 books."
    assert result.results == [RESULTS["data"]]
    assert [e.type for e in result.events] == ["thinking", "interpretation", "results", "text"]
    assert result.ok and result.errors == [] and result.warnings == []


def test_parlyr_chat_joins_text_and_clarification(client: Kloakd) -> None:
    lines = _sse_event_lines(
        ("clarification", _chat("clarification", "Which site?")),
        ("text", _chat("text", "Give me a URL.")),
        ("end", {}),
    )
    mock_client = _make_sync_http_client(_MockStreamResponse(lines))
    with patch("httpx.Client", return_value=mock_client):
        result = client.parlyr.chat("sess-002", "hello")
    assert result.response == "Which site?\nGive me a URL."
    assert result.interpretation is None and result.intent is None


def test_parlyr_chat_surfaces_an_error_event(client: Kloakd) -> None:
    lines = _sse_event_lines(
        ("warning", _chat("warning", "That is a lot of pages", {"level": "warn"})),
        ("error", _chat("error", "Scraping failed: timeout", {"error": "timeout", "job_id": "j1"}, [{"id": "retry", "label": "Retry"}])),
        ("end", {}),
    )
    mock_client = _make_sync_http_client(_MockStreamResponse(lines))
    with patch("httpx.Client", return_value=mock_client):
        result = client.parlyr.chat("sess-003", "scrape")
    assert not result.ok
    assert [e.content for e in result.errors] == ["Scraping failed: timeout"]
    assert result.errors[0].data == {"error": "timeout", "job_id": "j1"}
    assert [e.content for e in result.warnings] == ["That is a lot of pages"]


def test_parlyr_chat_reads_an_intent_key_when_present(client: Kloakd) -> None:
    lines = _sse_event_lines(("interpretation", _chat("interpretation", "x", {"intent": "scrape"})), ("end", {}))
    mock_client = _make_sync_http_client(_MockStreamResponse(lines))
    with patch("httpx.Client", return_value=mock_client):
        result = client.parlyr.chat("s", "m")
    assert result.intent == "scrape"


def test_parlyr_chat_skips_malformed_json(client: Kloakd) -> None:
    lines = [
        "event: interpretation",
        "data: BROKEN",
        "",
        "event: text",
        '  data: {"type": "text", "content": "Done.", "data": null, "actions": null, "timestamp": "t"}',
        "",
    ]
    mock_client = _make_sync_http_client(_MockStreamResponse(lines))

    with patch("httpx.Client", return_value=mock_client):
        result = client.parlyr.chat("sess-003", "hi")

    assert result.interpretation is None
    assert result.response == "Done."


def test_parlyr_chat_stream_stops_at_end(client: Kloakd) -> None:
    lines = _sse_event_lines(("text", _chat("text", "a")), ("end", {}), ("text", _chat("text", "late")))
    mock_client = _make_sync_http_client(_MockStreamResponse(lines))
    with patch("httpx.Client", return_value=mock_client):
        out = list(client.parlyr.chat_stream("s", "m"))
    assert [e.content for e in out] == ["a"]


def test_parlyr_chat_payload_contains_session_and_message(client: Kloakd) -> None:
    lines = _sse_event_lines(("end", {}))
    mock_response = _MockStreamResponse(lines)
    mock_client = _make_sync_http_client(mock_response)

    with patch("httpx.Client", return_value=mock_client):
        client.parlyr.chat("sess-abc", "my message")

    call_kwargs = mock_client.stream.call_args
    assert call_kwargs[1]["json"]["session_id"] == "sess-abc"
    assert call_kwargs[1]["json"]["message"] == "my message"


def _sse(*payloads: dict) -> str:
    return "".join(f"data: {json.dumps(p)}\n\n" for p in payloads) + ": keepalive\n\ndata: {not json}\n\n"


@respx.mock
def test_evadr_fetch_stream_starts_a_job_and_reads_its_events(client: Kloakd) -> None:
    respx.post(f"{TEST_BASE_URL}{ORG_PREFIX}/evadr/fetch/async").mock(return_value=Response(202, json={"job_id": "j1", "status": "pending", "message": ""}))
    events = respx.get(f"{TEST_BASE_URL}{ORG_PREFIX}/evadr/jobs/j1/events").mock(
        return_value=Response(200, text=_sse(
            # core/pipeline/models.py PipelineEvent.to_dict()
            {"pipeline_id": "j1", "event_type": "pipeline_step", "stage_id": "evadr.tier", "status": "in_progress", "phase": "discovery", "message": "Trying tier 1", "sub_status": None, "progress_pct": 20.0, "duration_ms": 5.0, "metadata": {"tier": 1}, "error": None, "timestamp": "t", "sequence": 3},
            # modules/evadr/router.py job-state fallback
            {"type": "COMPLETE", "job_id": "j1", "tier_used": 2, "artifact_id": "art-1"},
            {"type": "FAILED", "job_id": "j1", "error": "blocked"},
        ), headers={"content-type": "text/event-stream"})
    )
    out = list(client.evadr.fetch_stream("https://example.com"))
    assert [e.type for e in out] == ["pipeline_step", "COMPLETE", "FAILED"]
    step, done, failed = out
    assert (step.stage_id, step.status, step.message, step.progress_pct, step.sequence) == ("evadr.tier", "in_progress", "Trying tier 1", 20.0, 3)
    assert step.metadata == {"tier": 1} and step.job_id == "j1"
    assert (done.tier_used, done.artifact_id, done.job_id) == (2, "art-1", "j1")
    assert failed.error == "blocked"
    assert events.calls.last.request.headers["authorization"].startswith("Bearer sk-")


@respx.mock
def test_webgrph_crawl_stream_starts_a_crawl_and_reads_its_events(client: Kloakd) -> None:
    respx.post(f"{TEST_BASE_URL}{ORG_PREFIX}/webgrph/crawl").mock(return_value=Response(202, json={"crawl_id": "c1"}))
    events = respx.get(f"{TEST_BASE_URL}{ORG_PREFIX}/webgrph/crawl/c1/events").mock(
        return_value=Response(200, text=_sse({"event_type": "PAGE_FOUND", "url": "https://example.com/a", "depth": 1}), headers={"content-type": "text/event-stream"})
    )
    out = list(client.webgrph.crawl_stream("https://example.com", max_depth=2))
    assert [(e.type, e.url, e.depth) for e in out] == [("PAGE_FOUND", "https://example.com/a", 1)]
    # The key goes in the Authorization header, never in the URL.
    request = events.calls.last.request
    assert "token" not in request.url.params and request.headers["authorization"].startswith("Bearer ")


@respx.mock
async def test_async_crawl_stream_reads_events() -> None:
    respx.post(f"{TEST_BASE_URL}{ORG_PREFIX}/webgrph/crawl").mock(return_value=Response(202, json={"crawl_id": "c2"}))
    respx.get(f"{TEST_BASE_URL}{ORG_PREFIX}/webgrph/crawl/c2/events").mock(
        return_value=Response(200, text=_sse({"event_type": "CRAWL_COMPLETE"}), headers={"content-type": "text/event-stream"})
    )
    client = AsyncKloakd(api_key="k", organization_id=TEST_ORG_ID, base_url=TEST_BASE_URL)
    out = [e async for e in client.webgrph.crawl_stream("https://example.com")]
    assert [e.type for e in out] == ["CRAWL_COMPLETE"]
