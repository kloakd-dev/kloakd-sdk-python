"""
KLOAKD SDK — Skanyr module namespace.

Skanyr runs two-phase API discovery: Phase 1 maps the site structure
(or reuses a SITE_HIERARCHY artifact from Webgrph), Phase 2 actively
probes endpoints to build an API_MAP artifact.

Usage::

    # Discover APIs, seeding from a prior crawl
    discovery = client.skanyr.discover(
        "https://api.example.com",
        site_hierarchy_artifact_id=crawl.artifact_id,
    )
    print(f"Found {discovery.total_endpoints} endpoints")

    # Then extract via discovered APIs
    data = client.kolektr.page(
        "https://api.example.com/products",
        api_map_artifact_id=discovery.artifact_id,
    )
"""

from __future__ import annotations

import json as _json
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, AsyncIterator, Dict, List, Optional

from kloakd.models import ApiEndpoint, DiscoverEvent, DiscoverResult

if TYPE_CHECKING:
    from kloakd._http import _AsyncHttpTransport, _HttpTransport


def _parse_discover(raw: Dict[str, Any], url: str) -> DiscoverResult:
    endpoints = [
        ApiEndpoint(
            url=e.get("url", ""),
            method=e.get("method", "GET"),
            api_type=e.get("api_type", "unknown"),
            confidence=e.get("confidence", 0.0),
            parameters=e.get("parameters", {}),
        )
        for e in raw.get("endpoints", [])
    ]
    return DiscoverResult(
        success=raw.get("success", False),
        discovery_id=raw.get("discovery_id", ""),
        url=raw.get("url", url),
        total_endpoints=raw.get("total_endpoints", len(endpoints)),
        endpoints=endpoints,
        artifact_id=raw.get("artifact_id"),
        has_more=raw.get("has_more", False),
        total=raw.get("total", raw.get("total_endpoints", 0)),
        error=raw.get("error"),
    )


class SkanyrNamespace:
    """Synchronous Skanyr operations. Access via ``client.skanyr``."""

    def __init__(self, transport: "_HttpTransport") -> None:
        self._t = transport

    def discover(
        self,
        url: str,
        site_hierarchy_artifact_id: Optional[str] = None,
        max_requests: int = 200,
        session_artifact_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> DiscoverResult:
        """
        Run two-phase API discovery on a site.

        Args:
            url: Target base URL.
            site_hierarchy_artifact_id: SITE_HIERARCHY artifact from Webgrph
                (skips Phase 1 when provided).
            max_requests: Maximum requests during Phase 2 active probing.
            session_artifact_id: AUTHENTICATED_SESSION artifact from Fetchyr.
            limit: Max endpoints in this response.
            offset: Pagination offset.

        Returns:
            DiscoverResult with endpoints list and artifact_id.
        """
        body: Dict[str, Any] = {
            "url": url,
            "max_requests": max_requests,
            "limit": limit,
            "offset": offset,
        }
        if site_hierarchy_artifact_id:
            body["site_hierarchy_artifact_id"] = site_hierarchy_artifact_id
        if session_artifact_id:
            body["session_artifact_id"] = session_artifact_id

        raw = self._t.post("skanyr/discover", body)
        return _parse_discover(raw, url)

    def discover_all(
        self,
        url: str,
        site_hierarchy_artifact_id: Optional[str] = None,
        max_requests: int = 200,
        session_artifact_id: Optional[str] = None,
    ) -> List[ApiEndpoint]:
        """
        Auto-paginate discovery results, returning all discovered endpoints.

        Returns:
            Complete list of ApiEndpoint objects.
        """
        all_endpoints: List[ApiEndpoint] = []
        offset = 0
        while True:
            result = self.discover(
                url,
                site_hierarchy_artifact_id=site_hierarchy_artifact_id,
                max_requests=max_requests,
                session_artifact_id=session_artifact_id,
                limit=100,
                offset=offset,
            )
            all_endpoints.extend(result.endpoints)
            if not result.has_more:
                break
            offset += len(result.endpoints)
        return all_endpoints

    def get_api_map(self, artifact_id: str) -> Dict[str, Any]:
        """Retrieve a stored API_MAP artifact by ID."""
        return self._t.get(f"skanyr/api-map/{artifact_id}")

    def get_job(self, job_id: str) -> Dict[str, Any]:
        """Poll a discovery job by its job ID."""
        return self._t.get(f"skanyr/jobs/{job_id}")


class AsyncSkanyrNamespace:
    """Async Skanyr operations. Access via ``async_client.skanyr``."""

    def __init__(self, transport: "_AsyncHttpTransport") -> None:
        self._t = transport

    async def discover(
        self,
        url: str,
        site_hierarchy_artifact_id: Optional[str] = None,
        max_requests: int = 200,
        session_artifact_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> DiscoverResult:
        """Async equivalent of SkanyrNamespace.discover."""
        body: Dict[str, Any] = {
            "url": url,
            "max_requests": max_requests,
            "limit": limit,
            "offset": offset,
        }
        if site_hierarchy_artifact_id:
            body["site_hierarchy_artifact_id"] = site_hierarchy_artifact_id
        if session_artifact_id:
            body["session_artifact_id"] = session_artifact_id

        raw = await self._t.post("skanyr/discover", body)
        return _parse_discover(raw, url)

    @asynccontextmanager
    async def discover_stream(
        self,
        url: str,
        site_hierarchy_artifact_id: Optional[str] = None,
        max_requests: int = 200,
    ) -> AsyncIterator[AsyncIterator[DiscoverEvent]]:
        """
        Async SSE event stream for a Skanyr discovery run.

        Usage::

            async with client.skanyr.discover_stream("https://api.example.com") as events:
                async for event in events:
                    print(event.type, event.endpoint_url)
        """
        try:
            import httpx
        except ImportError as exc:
            raise RuntimeError("httpx is required for discover_stream") from exc

        url_path = self._t._url("skanyr/discover/stream")
        headers = self._t._auth_headers()
        headers["Accept"] = "text/event-stream"
        body: Dict[str, Any] = {"url": url, "max_requests": max_requests}
        if site_hierarchy_artifact_id:
            body["site_hierarchy_artifact_id"] = site_hierarchy_artifact_id

        async with httpx.AsyncClient(timeout=None) as http:
            async with http.stream("POST", url_path, json=body, headers=headers) as response:
                from kloakd._http import _HttpTransport
                _HttpTransport._raise_for_status(response.status_code, b"")

                async def _event_iter() -> AsyncIterator[DiscoverEvent]:
                    async for line in response.aiter_lines():
                        line = line.strip()
                        if not line.startswith("data:"):
                            continue
                        data_str = line[5:].strip()
                        if not data_str:
                            continue
                        try:
                            data = _json.loads(data_str)
                            yield DiscoverEvent(
                                type=data.get("type", ""),
                                endpoint_url=data.get("endpoint_url"),
                                api_type=data.get("api_type"),
                                metadata=data.get("metadata", {}),
                            )
                        except _json.JSONDecodeError:
                            continue

                yield _event_iter()

    async def get_api_map(self, artifact_id: str) -> Dict[str, Any]:
        """Async equivalent of SkanyrNamespace.get_api_map."""
        return await self._t.get(f"skanyr/api-map/{artifact_id}")

    async def get_job(self, job_id: str) -> Dict[str, Any]:
        """Async equivalent of SkanyrNamespace.get_job."""
        return await self._t.get(f"skanyr/jobs/{job_id}")
