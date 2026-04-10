"""
KLOAKD SDK — Client classes.

Provides two client classes:

    Kloakd      — synchronous (default, uses httpx.Client internally)
    AsyncKloakd — fully async (uses httpx.AsyncClient internally)

Both expose identical namespace APIs::

    client.evadr    — EvadrNamespace
    client.webgrph  — WebgrphNamespace
    client.skanyr   — SkanyrNamespace
    client.nexus    — NexusNamespace
    client.parlyr   — ParlyrNamespace
    client.fetchyr  — FetchyrNamespace
    client.kolektr  — KolektrNamespace
"""

from __future__ import annotations

from typing import Any, Optional

from kloakd._http import _AsyncHttpTransport, _HttpTransport
from kloakd.modules.evadr import AsyncEvadrNamespace, EvadrNamespace
from kloakd.modules.fetchyr import AsyncFetchyrNamespace, FetchyrNamespace
from kloakd.modules.kolektr import AsyncKolektrNamespace, KolektrNamespace
from kloakd.modules.nexus import AsyncNexusNamespace, NexusNamespace
from kloakd.modules.parlyr import AsyncParlyrNamespace, ParlyrNamespace
from kloakd.modules.skanyr import AsyncSkanyrNamespace, SkanyrNamespace
from kloakd.modules.webgrph import AsyncWebgrphNamespace, WebgrphNamespace

_DEFAULT_BASE_URL = "https://api.kloakd.dev"
_DEFAULT_TIMEOUT = 60.0
_DEFAULT_MAX_RETRIES = 3


class Kloakd:
    """
    KLOAKD API client — synchronous.

    The default client. All methods block until complete. For async/await
    usage, use AsyncKloakd instead.

    Args:
        api_key: Bearer API key (``sk-live-...`` or ``sk-test-...``).
            Generate at https://app.kloakd.dev/settings/api-keys.
        organization_id: Your organization UUID from the KLOAKD dashboard.
        base_url: API base URL. Defaults to ``https://api.kloakd.dev``.
        timeout: HTTP timeout in seconds. Defaults to 60.0.
        max_retries: Max retry attempts on retryable errors. Defaults to 3.
        http_client: Optional pre-built httpx.Client (useful in tests).

    Example::

        from kloakd import Kloakd

        client = Kloakd(
            api_key="sk-live-abc123",
            organization_id="your-org-uuid",
        )

        fetch = client.evadr.fetch("https://books.toscrape.com")
        data  = client.kolektr.page(
            "https://books.toscrape.com",
            schema={"title": "css:h3 a", "price": "css:p.price_color"},
            fetch_artifact_id=fetch.artifact_id,
        )
        print(data.records[:3])
    """

    def __init__(
        self,
        api_key: str,
        organization_id: str,
        base_url: str = _DEFAULT_BASE_URL,
        timeout: float = _DEFAULT_TIMEOUT,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        http_client: Optional[Any] = None,
    ) -> None:
        if not api_key or not api_key.strip():
            raise ValueError("Kloakd: api_key is required")
        if not organization_id or not organization_id.strip():
            raise ValueError("Kloakd: organization_id is required")

        self._transport = _HttpTransport(
            api_key=api_key,
            organization_id=organization_id,
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries,
            http_client=http_client,
        )

        self.evadr = EvadrNamespace(self._transport)
        self.webgrph = WebgrphNamespace(self._transport)
        self.skanyr = SkanyrNamespace(self._transport)
        self.nexus = NexusNamespace(self._transport)
        self.parlyr = ParlyrNamespace(self._transport)
        self.fetchyr = FetchyrNamespace(self._transport)
        self.kolektr = KolektrNamespace(self._transport)

    def __repr__(self) -> str:
        return (
            f"Kloakd(organization_id={self._transport._organization_id!r}, "
            f"base_url={self._transport._base_url!r})"
        )


class AsyncKloakd:
    """
    KLOAKD API client — fully asynchronous.

    All namespace methods are coroutines (must be awaited). SSE stream
    methods are async context managers yielding async iterators.

    Args:
        api_key: Bearer API key.
        organization_id: Your organization UUID.
        base_url: API base URL. Defaults to ``https://api.kloakd.dev``.
        timeout: HTTP timeout in seconds. Defaults to 60.0.
        max_retries: Max retry attempts on retryable errors. Defaults to 3.
        http_client: Optional pre-built httpx.AsyncClient (useful in tests).

    Example::

        from kloakd import AsyncKloakd

        client = AsyncKloakd(
            api_key="sk-live-abc123",
            organization_id="your-org-uuid",
        )

        async def main():
            fetch = await client.evadr.fetch("https://books.toscrape.com")
            data  = await client.kolektr.page(
                "https://books.toscrape.com",
                fetch_artifact_id=fetch.artifact_id,
            )
            print(data.records[:3])

            # SSE stream
            async with client.webgrph.crawl_stream("https://books.toscrape.com") as events:
                async for event in events:
                    print(event.type, event.url)
    """

    def __init__(
        self,
        api_key: str,
        organization_id: str,
        base_url: str = _DEFAULT_BASE_URL,
        timeout: float = _DEFAULT_TIMEOUT,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        http_client: Optional[Any] = None,
    ) -> None:
        if not api_key or not api_key.strip():
            raise ValueError("AsyncKloakd: api_key is required")
        if not organization_id or not organization_id.strip():
            raise ValueError("AsyncKloakd: organization_id is required")

        self._transport = _AsyncHttpTransport(
            api_key=api_key,
            organization_id=organization_id,
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries,
            http_client=http_client,
        )

        self.evadr = AsyncEvadrNamespace(self._transport)
        self.webgrph = AsyncWebgrphNamespace(self._transport)
        self.skanyr = AsyncSkanyrNamespace(self._transport)
        self.nexus = AsyncNexusNamespace(self._transport)
        self.parlyr = AsyncParlyrNamespace(self._transport)
        self.fetchyr = AsyncFetchyrNamespace(self._transport)
        self.kolektr = AsyncKolektrNamespace(self._transport)

    def __repr__(self) -> str:
        return (
            f"AsyncKloakd(organization_id={self._transport._organization_id!r}, "
            f"base_url={self._transport._base_url!r})"
        )
