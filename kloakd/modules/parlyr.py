"""
KLOAKD SDK — Parlyr module namespace.

Parlyr is KLOAKD's Conversational NLP layer — a 3-tier intent parser that
resolves natural language scraping commands into structured extraction jobs.

Usage::

    # Stateless parse (fast, no session)
    parsed = client.parlyr.parse("Scrape all product names and prices from amazon.com")
    print(parsed.intent, parsed.detected_url, parsed.entities)

    # Full chat turn (blocks until complete)
    turn = client.parlyr.chat(session_id="my-session", message="Get reviews too")
    print(turn.response)
"""

from __future__ import annotations

import json as _json
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, AsyncIterator, Dict, Optional

from kloakd.models import ChatEvent, ChatTurn, ParseResult

if TYPE_CHECKING:
    from kloakd._http import _AsyncHttpTransport, _HttpTransport


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
        Send one chat turn and collect all SSE events into a ChatTurn.

        Blocks until the ``done`` event is received. Use chat_stream()
        on AsyncKloakd for non-blocking streaming.

        Args:
            session_id: Stable session identifier (you choose the value).
            message: User's message for this turn.

        Returns:
            ChatTurn with intent, response text, and entities.
        """
        try:
            import httpx
        except ImportError as exc:
            raise RuntimeError("httpx is required: pip install kloakd-sdk") from exc

        url = self._t._url("parlyr/chat")
        headers = self._t._auth_headers()
        headers["Accept"] = "text/event-stream"

        intent_data: Dict[str, Any] = {}
        response_text = ""

        with httpx.Client(timeout=self._t._timeout) as http:
            with http.stream(
                "POST",
                url,
                json={"session_id": session_id, "message": message},
                headers=headers,
            ) as resp:
                from kloakd._http import _HttpTransport
                _HttpTransport._raise_for_status(resp.status_code, b"")
                current_event = ""
                for line in resp.iter_lines():
                    line = line.strip()
                    if line.startswith("event:"):
                        current_event = line[6:].strip()
                    elif line.startswith("data:"):
                        data_str = line[5:].strip()
                        if not data_str:
                            continue
                        try:
                            data = _json.loads(data_str)
                        except _json.JSONDecodeError:
                            continue
                        if current_event == "intent":
                            intent_data = data
                        elif current_event == "response":
                            response_text = data.get("content", "")

        return ChatTurn(
            session_id=session_id,
            intent=intent_data.get("intent", "unknown"),
            confidence=intent_data.get("confidence", 0.0),
            tier=intent_data.get("tier", 0),
            response=response_text,
            entities=intent_data.get("entities", {}),
            requires_action=intent_data.get("requires_action", False),
            clarification_needed=intent_data.get("clarification_needed"),
        )

    def delete_session(self, session_id: str) -> None:
        """
        Delete a Parlyr chat session and all its history.

        Args:
            session_id: Session to delete.
        """
        self._t.delete(f"parlyr/chat/{session_id}")


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
                    print(event.event, event.data)
        """
        try:
            import httpx
        except ImportError as exc:
            raise RuntimeError("httpx is required for chat_stream") from exc

        url = self._t._url("parlyr/chat")
        headers = self._t._auth_headers()
        headers["Accept"] = "text/event-stream"

        async with httpx.AsyncClient(timeout=None) as http:
            async with http.stream(
                "POST",
                url,
                json={"session_id": session_id, "message": message},
                headers=headers,
            ) as response:
                from kloakd._http import _HttpTransport
                _HttpTransport._raise_for_status(response.status_code, b"")

                async def _event_iter() -> AsyncIterator[ChatEvent]:
                    current_event = ""
                    async for line in response.aiter_lines():
                        line = line.strip()
                        if line.startswith("event:"):
                            current_event = line[6:].strip()
                        elif line.startswith("data:"):
                            data_str = line[5:].strip()
                            if not data_str:
                                continue
                            try:
                                data = _json.loads(data_str)
                            except _json.JSONDecodeError:
                                continue
                            yield ChatEvent(event=current_event, data=data)

                yield _event_iter()

    async def delete_session(self, session_id: str) -> None:
        """Async equivalent of ParlyrNamespace.delete_session."""
        await self._t.delete(f"parlyr/chat/{session_id}")
