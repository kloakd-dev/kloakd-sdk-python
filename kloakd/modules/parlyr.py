"""
KLOAKD SDK — Parlyr module namespace.

Parlyr is KLOAKD's Conversational NLP layer — a 3-tier intent parser that
resolves natural language scraping commands into structured extraction jobs.

Usage::

    # Stateless parse (fast, no session)
    parsed = client.parlyr.parse("Scrape all product names and prices from amazon.com")
    print(parsed.intent, parsed.detected_url, parsed.entities)

    # Full chat turn (blocks until the stream ends)
    turn = client.parlyr.chat(session_id="my-session", message="Get reviews too")
    print(turn.response, turn.interpretation, turn.results)

The chat route streams Server-Sent Events whose payload is
``{type, content, data, actions, timestamp}`` and closes with ``end``
(kobe-scraper application/services/chat_orchestrator.py ChatEvent,
modules/parlyr/router.py).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, AsyncIterator, Dict, Iterator, List, Optional

from kloakd.models import ChatEvent, ChatTurn, ParseResult
from kloakd.modules._ops import seg

if TYPE_CHECKING:
    from kloakd._http import _AsyncHttpTransport, _HttpTransport


_END = "end"


def _chat_body(session_id: str, message: str) -> Dict[str, Any]:
    return {"session_id": session_id, "message": message}


def _chat_event(name: str, data: Dict[str, Any]) -> ChatEvent:
    raw_data = data.get("data")
    raw_actions = data.get("actions")
    return ChatEvent(
        type=str(data.get("type") or name),
        content=data.get("content"),
        data=raw_data if isinstance(raw_data, dict) else None,
        actions=raw_actions if isinstance(raw_actions, list) else None,
        timestamp=data.get("timestamp"),
    )


class _TurnBuilder:
    """Collects one turn's events into a ChatTurn."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.events: List[ChatEvent] = []

    def add(self, event: ChatEvent) -> None:
        self.events.append(event)

    def turn(self) -> ChatTurn:
        texts = [
            e.content
            for e in self.events
            if e.type in ("text", "clarification") and e.content
        ]
        interpretation: Optional[Dict[str, Any]] = None
        for e in self.events:
            if e.type == "interpretation" and e.data is not None:
                interpretation = e.data
        intent = (interpretation or {}).get("intent")
        return ChatTurn(
            session_id=self.session_id,
            response="\n".join(texts),
            intent=str(intent) if intent is not None else None,
            interpretation=interpretation,
            results=[
                e.data for e in self.events if e.type == "results" and e.data is not None
            ],
            errors=[e for e in self.events if e.type == "error"],
            warnings=[e for e in self.events if e.type == "warning"],
            events=list(self.events),
        )


class ParlyrNamespace:
    """Synchronous Parlyr operations. Access via ``client.parlyr``."""

    def __init__(self, transport: "_HttpTransport") -> None:
        self._t = transport

    def parse(
        self,
        message: str,
        session_id: Optional[str] = None,
    ) -> ParseResult:
        """
        Stateless 3-tier intent parse — no session state, ultra-fast.

        Args:
            message: Natural language scraping intent.
            session_id: Optional session ID for Tier 1 context-aware matching.

        Returns:
            ParseResult with intent, confidence, tier, and entities.
        """
        body: Dict[str, Any] = {"message": message}
        if session_id:
            body["session_id"] = session_id

        raw = self._t.post("parlyr/parse", body)
        return ParseResult(
            intent=raw.get("intent", "unknown"),
            confidence=raw.get("confidence", 0.0),
            tier=raw.get("tier", 0),
            source=raw.get("source", ""),
            entities=raw.get("entities", {}),
            requires_action=raw.get("requires_action", False),
            clarification_needed=raw.get("clarification_needed"),
            reasoning=raw.get("reasoning"),
            detected_url=raw.get("detected_url"),
        )

    def chat(self, session_id: str, message: str) -> ChatTurn:
        """
        Send one chat turn and collect its SSE events into a ChatTurn.

        Blocks until the stream's ``end`` event. ``response`` joins the
        ``text`` and ``clarification`` events' content with newlines;
        ``interpretation`` is the ``interpretation`` event's data (and
        ``intent`` its ``intent`` key, if any); ``results`` holds each
        ``results`` event's data; ``error`` and ``warning`` events are
        collected in ``errors`` and ``warnings`` (an error is not raised;
        ``ok`` is then False). Every event is kept in ``events``.

        Args:
            session_id: Stable session identifier (you choose the value).
            message: User's message for this turn.
        """
        builder = _TurnBuilder(session_id)
        for event in self.chat_stream(session_id, message):
            builder.add(event)
        return builder.turn()

    def chat_stream(self, session_id: str, message: str) -> Iterator[ChatEvent]:
        """Yield the events of one chat turn as they arrive (up to ``end``)."""
        for name, data in self._t.iter_sse(
            "POST", "parlyr/chat", _chat_body(session_id, message)
        ):
            if name == _END:
                return
            yield _chat_event(name, data)

    def delete_session(self, session_id: str) -> None:
        """
        Delete a Parlyr chat session and all its history.

        Args:
            session_id: Session to delete.
        """
        self._t.delete(f"parlyr/chat/{seg(session_id)}")


class AsyncParlyrNamespace:
    """Async Parlyr operations. Access via ``async_client.parlyr``."""

    def __init__(self, transport: "_AsyncHttpTransport") -> None:
        self._t = transport

    async def parse(
        self,
        message: str,
        session_id: Optional[str] = None,
    ) -> ParseResult:
        """Async equivalent of ParlyrNamespace.parse."""
        body: Dict[str, Any] = {"message": message}
        if session_id:
            body["session_id"] = session_id
        raw = await self._t.post("parlyr/parse", body)
        return ParseResult(
            intent=raw.get("intent", "unknown"),
            confidence=raw.get("confidence", 0.0),
            tier=raw.get("tier", 0),
            source=raw.get("source", ""),
            entities=raw.get("entities", {}),
            requires_action=raw.get("requires_action", False),
            clarification_needed=raw.get("clarification_needed"),
            reasoning=raw.get("reasoning"),
            detected_url=raw.get("detected_url"),
        )

    @asynccontextmanager
    async def chat_stream(
        self,
        session_id: str,
        message: str,
    ) -> AsyncIterator[AsyncIterator[ChatEvent]]:
        """
        Async SSE event stream for one chat turn.

        Usage::

            async with client.parlyr.chat_stream("sess-1", "Scrape linkedin.com") as events:
                async for event in events:
                    print(event.type, event.content, event.data)
        """
        yield self._events(session_id, message)

    async def _events(self, session_id: str, message: str) -> AsyncIterator[ChatEvent]:
        async for name, data in self._t.aiter_sse(
            "POST", "parlyr/chat", _chat_body(session_id, message)
        ):
            if name == _END:
                return
            yield _chat_event(name, data)

    async def chat(self, session_id: str, message: str) -> ChatTurn:
        """Async equivalent of ParlyrNamespace.chat."""
        builder = _TurnBuilder(session_id)
        async for event in self._events(session_id, message):
            builder.add(event)
        return builder.turn()

    async def delete_session(self, session_id: str) -> None:
        """Async equivalent of ParlyrNamespace.delete_session."""
        await self._t.delete(f"parlyr/chat/{seg(session_id)}")
