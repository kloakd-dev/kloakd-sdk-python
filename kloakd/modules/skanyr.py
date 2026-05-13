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

    def get_discovery(self, discovery_id: str) -> Dict[str, Any]:
        """Poll discovery status by ID."""
        return self._t.get(f"skanyr/discover/{discovery_id}")

    def get_discovery_events(self, discovery_id: str) -> Dict[str, Any]:
        """Get SSE stream events for a discovery run."""
        return self._t.get(f"skanyr/discover/{discovery_id}/events")

    def analyze_bundle(self, url: str) -> Dict[str, Any]:
        """
        Analyse a specific JS bundle URL for embedded API patterns.

        Args:
            url: URL of the JavaScript bundle to analyse.

        Returns:
            Dict with detected API patterns and endpoints.
        """
        return self._t.post("skanyr/analyze-bundle", {"url": url})

    def discover_page_live(self, url: str) -> Dict[str, Any]:
        """
        Live page discovery — runs all detectors against a single page.

        Args:
            url: Target page URL.

        Returns:
            Dict with live discovery results.
        """
        return self._t.post("skanyr/discover-page/live", {"url": url})

    def detected_apis(self, page_url: str) -> Dict[str, Any]:
        """
        List all detected APIs from a prior discovery run.

        Args:
            page_url: URL of the page that was discovered.

        Returns:
            Dict with detectors list and total_records.
        """
        return self._t.get("skanyr/detected-apis", params={"page_url": page_url})

    def hierarchy(self, url: str) -> Dict[str, Any]:
        """
        Discover site hierarchy from a URL.

        Args:
            url: Target URL.

        Returns:
            Dict with hierarchy tree.
        """
        return self._t.post("skanyr/hierarchy", {"url": url})

    def expand_node(self, node_id: str) -> Dict[str, Any]:
        """
        Expand a hierarchy node to discover child pages.

        Args:
            node_id: Node identifier from hierarchy().

        Returns:
            Dict with expanded children.
        """
        return self._t.post("skanyr/expand-node", {"node_id": node_id})

    def reader_view(self, url: str) -> Dict[str, Any]:
        """
        Extract a clean reader view of a page.

        Args:
            url: Target URL.

        Returns:
            Dict with cleaned content.
        """
        return self._t.post("skanyr/reader-view", {"url": url})

    def retry(self, discovery_id: str, overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Retry a discovery run with optional overrides.

        Args:
            discovery_id: ID of the original discovery.
            overrides: Optional parameter overrides.

        Returns:
            New discovery result.
        """
        body: Dict[str, Any] = {"discovery_id": discovery_id}
        if overrides:
            body.update(overrides)
        return self._t.post("skanyr/retry", body)

    def health(self) -> Dict[str, Any]:
        """Health check for Skanyr discovery service."""
        return self._t.get("skanyr/health")

    # ── Session management ─────────────────────────────────────────────

    def list_sessions(self) -> Dict[str, Any]:
        """List discovery sessions."""
        return self._t.get("skanyr/sessions")

    def save_session(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Save a discovery session."""
        return self._t.post("skanyr/sessions", config)

    def get_session(self, session_id: str) -> Dict[str, Any]:
        """Get a discovery session by ID."""
        return self._t.get(f"skanyr/sessions/{session_id}")

    def delete_session(self, session_id: str) -> None:
        """Delete a discovery session."""
        self._t.delete(f"skanyr/sessions/{session_id}")

    def end_session(self, session_id: str) -> Dict[str, Any]:
        """End an active discovery session."""
        return self._t.post(f"skanyr/sessions/{session_id}/end", {})

    def update_session_job(self, session_id: str, job_id: str) -> Dict[str, Any]:
        """Update the job ID associated with a session."""
        return self._t.patch(f"skanyr/sessions/{session_id}/job", {"job_id": job_id})

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

    async def get_discovery(self, discovery_id: str) -> Dict[str, Any]:
        """Async equivalent of SkanyrNamespace.get_discovery."""
        return await self._t.get(f"skanyr/discover/{discovery_id}")

    async def get_discovery_events(self, discovery_id: str) -> Dict[str, Any]:
        """Async equivalent of SkanyrNamespace.get_discovery_events."""
        return await self._t.get(f"skanyr/discover/{discovery_id}/events")

    async def analyze_bundle(self, url: str) -> Dict[str, Any]:
        """Async equivalent of SkanyrNamespace.analyze_bundle."""
        return await self._t.post("skanyr/analyze-bundle", {"url": url})

    async def discover_page_live(self, url: str) -> Dict[str, Any]:
        """Async equivalent of SkanyrNamespace.discover_page_live."""
        return await self._t.post("skanyr/discover-page/live", {"url": url})

    async def detected_apis(self, page_url: str) -> Dict[str, Any]:
        """Async equivalent of SkanyrNamespace.detected_apis."""
        return await self._t.get("skanyr/detected-apis", params={"page_url": page_url})

    async def hierarchy(self, url: str) -> Dict[str, Any]:
        """Async equivalent of SkanyrNamespace.hierarchy."""
        return await self._t.post("skanyr/hierarchy", {"url": url})

    async def expand_node(self, node_id: str) -> Dict[str, Any]:
        """Async equivalent of SkanyrNamespace.expand_node."""
        return await self._t.post("skanyr/expand-node", {"node_id": node_id})

    async def reader_view(self, url: str) -> Dict[str, Any]:
        """Async equivalent of SkanyrNamespace.reader_view."""
        return await self._t.post("skanyr/reader-view", {"url": url})

    async def retry(self, discovery_id: str, overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Async equivalent of SkanyrNamespace.retry."""
        body: Dict[str, Any] = {"discovery_id": discovery_id}
        if overrides:
            body.update(overrides)
        return await self._t.post("skanyr/retry", body)

    async def health(self) -> Dict[str, Any]:
        """Async equivalent of SkanyrNamespace.health."""
        return await self._t.get("skanyr/health")

    async def list_sessions(self) -> Dict[str, Any]:
        """Async equivalent of SkanyrNamespace.list_sessions."""
        return await self._t.get("skanyr/sessions")

    async def save_session(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Async equivalent of SkanyrNamespace.save_session."""
        return await self._t.post("skanyr/sessions", config)

    async def get_session(self, session_id: str) -> Dict[str, Any]:
        """Async equivalent of SkanyrNamespace.get_session."""
        return await self._t.get(f"skanyr/sessions/{session_id}")

    async def delete_session(self, session_id: str) -> None:
        """Async equivalent of SkanyrNamespace.delete_session."""
        await self._t.delete(f"skanyr/sessions/{session_id}")

    async def end_session(self, session_id: str) -> Dict[str, Any]:
        """Async equivalent of SkanyrNamespace.end_session."""
        return await self._t.post(f"skanyr/sessions/{session_id}/end", {})

    async def update_session_job(self, session_id: str, job_id: str) -> Dict[str, Any]:
        """Async equivalent of SkanyrNamespace.update_session_job."""
        return await self._t.patch(f"skanyr/sessions/{session_id}/job", {"job_id": job_id})

    async def get_api_map(self, artifact_id: str) -> Dict[str, Any]:
        """Async equivalent of SkanyrNamespace.get_api_map."""
        return await self._t.get(f"skanyr/api-map/{artifact_id}")

    async def get_job(self, job_id: str) -> Dict[str, Any]:
        """Async equivalent of SkanyrNamespace.get_job."""
        return await self._t.get(f"skanyr/jobs/{job_id}")
