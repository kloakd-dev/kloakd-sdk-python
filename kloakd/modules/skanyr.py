"""
KLOAKD SDK — Skanyr module namespace.

Skanyr is the site knowledge store: sites built from crawls, their
resources, search, change history, the resource graph and technology
findings.

Usage::

    crawl = client.webgrph.crawl("https://example.com")
    site = client.skanyr.site_from_crawl(crawl.crawl_id)
    hits = client.skanyr.search("pricing", site_id=site["site_id"])

The 0.2 discovery methods (discover, hierarchy, expand_node, …) called
routes the API no longer has; page discovery is ``webgrph.crawl``, and
sessions, reader view and detected APIs moved to ``webgrph``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional

from kloakd.modules._ops import _Op, arun, as_list, compact, run, seg

if TYPE_CHECKING:
    from kloakd._http import _AsyncHttpTransport, _HttpTransport


def _text(raw: Any) -> str:
    return raw if isinstance(raw, str) else ""


class SkanyrNamespace:
    """Synchronous Skanyr operations. Access via ``client.skanyr``."""

    def __init__(self, transport: "_HttpTransport") -> None:
        self._t = transport

    def list_sites(self) -> List[Dict[str, Any]]:
        return run(self._t, _Op("GET", "skanyr/sites", parse=as_list))

    def site_from_crawl(self, crawl_id: str) -> Dict[str, Any]:
        """Build (or update) a site from a finished crawl."""
        return run(self._t, _Op("POST", f"skanyr/sites/from-crawl/{seg(crawl_id)}", {}))

    def get_site(self, site_id: str) -> Dict[str, Any]:
        return run(self._t, _Op("GET", f"skanyr/sites/{seg(site_id)}"))

    def update_site(
        self, site_id: str, policy: str
    ) -> Dict[str, Any]:
        """Set a site's default sync policy: ``full``, ``incremental``,
        ``conditional`` or ``head_first`` (modules/skanyr/router.py SiteUpdateRequest)."""
        return run(
            self._t,
            _Op("PATCH", f"skanyr/sites/{seg(site_id)}", {"policy": policy}),
        )

    def delete_site(self, site_id: str) -> None:
        run(self._t, _Op("DELETE", f"skanyr/sites/{seg(site_id)}"))

    def sync(
        self,
        site_id: str,
        urls: Optional[List[str]] = None,
        policy: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Re-fetch a site's changed content (all of it, or the given URLs)."""
        return run(
            self._t,
            _Op(
                "POST",
                "skanyr/sync",
                compact({"site_id": site_id, "urls": urls, "policy": policy}),
            ),
        )

    def export_site(
        self,
        site_id: str,
        resource_ids: Optional[List[str]] = None,
        max_bytes: Optional[int] = None,
    ) -> bytes:
        """The site's captured content as a ZIP archive (raw bytes)."""
        return self._t.request_bytes(
            "POST",
            f"skanyr/sites/{seg(site_id)}/export",
            json_body=compact({"resource_ids": resource_ids, "max_bytes": max_bytes}),
        )

    def get_site_apis(
        self, site_id: str, limit: Optional[int] = None, offset: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        return run(
            self._t,
            _Op(
                "GET",
                f"skanyr/sites/{seg(site_id)}/apis",
                params=compact({"limit": limit, "offset": offset}),
                parse=as_list,
            ),
        )

    def get_site_resources(
        self,
        site_id: str,
        resource_type: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        return run(
            self._t,
            _Op(
                "GET",
                f"skanyr/sites/{seg(site_id)}/resources",
                params=compact(
                    {"resource_type": resource_type, "limit": limit, "offset": offset}
                ),
                parse=as_list,
            ),
        )

    def search_site(
        self,
        site_id: str,
        q: str,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        mime_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        return run(
            self._t,
            _Op(
                "GET",
                f"skanyr/sites/{seg(site_id)}/search",
                params=compact(
                    {"q": q, "limit": limit, "offset": offset, "mime_type": mime_type}
                ),
            ),
        )

    def get_findings(
        self,
        site_id: str,
        finding_kind: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        return run(
            self._t,
            _Op(
                "GET",
                f"skanyr/sites/{seg(site_id)}/findings",
                params=compact(
                    {"finding_kind": finding_kind, "limit": limit, "offset": offset}
                ),
                parse=as_list,
            ),
        )

    def get_technologies(self, site_id: str) -> List[Dict[str, Any]]:
        return run(self._t, _Op("GET", f"skanyr/sites/{seg(site_id)}/technologies", parse=as_list))

    def get_technology_evidence(
        self,
        site_id: str,
        subject: str,
        detector: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> Dict[str, Any]:
        return run(
            self._t,
            _Op(
                "GET",
                f"skanyr/sites/{seg(site_id)}/technology-evidence",
                params=compact(
                    {
                        "subject": subject,
                        "detector": detector,
                        "limit": limit,
                        "offset": offset,
                    }
                ),
            ),
        )

    def list_snapshots(
        self, site_id: str, limit: Optional[int] = None
    ) -> Dict[str, Any]:
        return run(
            self._t,
            _Op(
                "GET",
                f"skanyr/sites/{seg(site_id)}/snapshots",
                params=compact({"limit": limit}),
            ),
        )

    def get_timeline(self, site_id: str, limit: Optional[int] = None) -> Dict[str, Any]:
        return run(
            self._t,
            _Op(
                "GET",
                f"skanyr/sites/{seg(site_id)}/timeline",
                params=compact({"limit": limit}),
            ),
        )

    def get_timeline_snapshot(self, site_id: str, snapshot_id: str) -> Dict[str, Any]:
        return run(
            self._t, _Op("GET", f"skanyr/sites/{seg(site_id)}/timeline/{seg(snapshot_id)}")
        )

    def diff(
        self,
        site_id: str,
        snapshot_a: Optional[str] = None,
        snapshot_b: Optional[str] = None,
    ) -> Dict[str, Any]:
        return run(
            self._t,
            _Op(
                "GET",
                f"skanyr/sites/{seg(site_id)}/diff",
                params=compact({"snapshot_a": snapshot_a, "snapshot_b": snapshot_b}),
            ),
        )

    def get_graph(
        self,
        site_id: str,
        resource_type: Optional[str] = None,
        max_depth: Optional[int] = None,
        edge_kind: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Dict[str, Any]:
        return run(
            self._t,
            _Op(
                "GET",
                f"skanyr/sites/{seg(site_id)}/graph",
                params=compact(
                    {
                        "resource_type": resource_type,
                        "max_depth": max_depth,
                        "edge_kind": edge_kind,
                        "limit": limit,
                    }
                ),
            ),
        )

    def get_graph_stats(self, site_id: str) -> Dict[str, Any]:
        return run(self._t, _Op("GET", f"skanyr/sites/{seg(site_id)}/graph/stats"))

    def get_subgraph(
        self, site_id: str, resource_id: str, hops: Optional[int] = None
    ) -> Dict[str, Any]:
        return run(
            self._t,
            _Op(
                "GET",
                f"skanyr/sites/{seg(site_id)}/graph/subgraph/{seg(resource_id)}",
                params=compact({"hops": hops}),
            ),
        )

    def list_resources(
        self,
        site_id: Optional[str] = None,
        resource_type: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        return run(
            self._t,
            _Op(
                "GET",
                "skanyr/resources",
                params=compact(
                    {
                        "site_id": site_id,
                        "resource_type": resource_type,
                        "limit": limit,
                        "offset": offset,
                    }
                ),
                parse=as_list,
            ),
        )

    def get_resource(self, resource_id: str) -> Dict[str, Any]:
        return run(self._t, _Op("GET", f"skanyr/resources/{seg(resource_id)}"))

    def search(
        self,
        query: str,
        site_id: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        mime_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Full-text search across the organisation's stored content."""
        return run(
            self._t,
            _Op(
                "POST",
                "skanyr/search",
                compact(
                    {
                        "query": query,
                        "site_id": site_id,
                        "limit": limit,
                        "offset": offset,
                        "mime_type": mime_type,
                    }
                ),
            ),
        )

    def extract(
        self,
        content_hash: str,
        mime_type: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Extract text and structure from stored content (by its content hash)."""
        return run(
            self._t,
            _Op(
                "POST",
                "skanyr/extract",
                {
                    "content_hash": content_hash,
                    "mime_type": mime_type,
                    "metadata": metadata or {},
                },
            ),
        )

    def get_extraction_text(self, content_hash: str) -> str:
        """The extracted plain text (the API answers text/plain)."""
        return run(self._t, _Op("GET", f"skanyr/extractions/{seg(content_hash)}/text", parse=_text))

    def get_extraction_structure(self, content_hash: str) -> Dict[str, Any]:
        return run(self._t, _Op("GET", f"skanyr/extractions/{seg(content_hash)}/structure"))


class AsyncSkanyrNamespace:
    """Async Skanyr operations. Access via ``async_client.skanyr``."""

    def __init__(self, transport: "_AsyncHttpTransport") -> None:
        self._t = transport

    async def list_sites(self) -> List[Dict[str, Any]]:
        return await arun(self._t, _Op("GET", "skanyr/sites", parse=as_list))

    async def site_from_crawl(self, crawl_id: str) -> Dict[str, Any]:
        """Build (or update) a site from a finished crawl."""
        return await arun(
            self._t, _Op("POST", f"skanyr/sites/from-crawl/{seg(crawl_id)}", {})
        )

    async def get_site(self, site_id: str) -> Dict[str, Any]:
        return await arun(self._t, _Op("GET", f"skanyr/sites/{seg(site_id)}"))

    async def update_site(
        self, site_id: str, policy: str
    ) -> Dict[str, Any]:
        """Set a site's default sync policy: ``full``, ``incremental``,
        ``conditional`` or ``head_first`` (modules/skanyr/router.py SiteUpdateRequest)."""
        return await arun(
            self._t,
            _Op("PATCH", f"skanyr/sites/{seg(site_id)}", {"policy": policy}),
        )

    async def delete_site(self, site_id: str) -> None:
        await arun(self._t, _Op("DELETE", f"skanyr/sites/{seg(site_id)}"))

    async def sync(
        self,
        site_id: str,
        urls: Optional[List[str]] = None,
        policy: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Re-fetch a site's changed content (all of it, or the given URLs)."""
        return await arun(
            self._t,
            _Op(
                "POST",
                "skanyr/sync",
                compact({"site_id": site_id, "urls": urls, "policy": policy}),
            ),
        )

    async def export_site(
        self,
        site_id: str,
        resource_ids: Optional[List[str]] = None,
        max_bytes: Optional[int] = None,
    ) -> bytes:
        """The site's captured content as a ZIP archive (raw bytes)."""
        return await self._t.request_bytes(
            "POST",
            f"skanyr/sites/{seg(site_id)}/export",
            json_body=compact({"resource_ids": resource_ids, "max_bytes": max_bytes}),
        )

    async def get_site_apis(
        self, site_id: str, limit: Optional[int] = None, offset: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        return await arun(
            self._t,
            _Op(
                "GET",
                f"skanyr/sites/{seg(site_id)}/apis",
                params=compact({"limit": limit, "offset": offset}),
                parse=as_list,
            ),
        )

    async def get_site_resources(
        self,
        site_id: str,
        resource_type: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        return await arun(
            self._t,
            _Op(
                "GET",
                f"skanyr/sites/{seg(site_id)}/resources",
                params=compact(
                    {"resource_type": resource_type, "limit": limit, "offset": offset}
                ),
                parse=as_list,
            ),
        )

    async def search_site(
        self,
        site_id: str,
        q: str,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        mime_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        return await arun(
            self._t,
            _Op(
                "GET",
                f"skanyr/sites/{seg(site_id)}/search",
                params=compact(
                    {"q": q, "limit": limit, "offset": offset, "mime_type": mime_type}
                ),
            ),
        )

    async def get_findings(
        self,
        site_id: str,
        finding_kind: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        return await arun(
            self._t,
            _Op(
                "GET",
                f"skanyr/sites/{seg(site_id)}/findings",
                params=compact(
                    {"finding_kind": finding_kind, "limit": limit, "offset": offset}
                ),
                parse=as_list,
            ),
        )

    async def get_technologies(self, site_id: str) -> List[Dict[str, Any]]:
        return await arun(self._t, _Op("GET", f"skanyr/sites/{seg(site_id)}/technologies", parse=as_list))

    async def get_technology_evidence(
        self,
        site_id: str,
        subject: str,
        detector: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> Dict[str, Any]:
        return await arun(
            self._t,
            _Op(
                "GET",
                f"skanyr/sites/{seg(site_id)}/technology-evidence",
                params=compact(
                    {
                        "subject": subject,
                        "detector": detector,
                        "limit": limit,
                        "offset": offset,
                    }
                ),
            ),
        )

    async def list_snapshots(
        self, site_id: str, limit: Optional[int] = None
    ) -> Dict[str, Any]:
        return await arun(
            self._t,
            _Op(
                "GET",
                f"skanyr/sites/{seg(site_id)}/snapshots",
                params=compact({"limit": limit}),
            ),
        )

    async def get_timeline(
        self, site_id: str, limit: Optional[int] = None
    ) -> Dict[str, Any]:
        return await arun(
            self._t,
            _Op(
                "GET",
                f"skanyr/sites/{seg(site_id)}/timeline",
                params=compact({"limit": limit}),
            ),
        )

    async def get_timeline_snapshot(
        self, site_id: str, snapshot_id: str
    ) -> Dict[str, Any]:
        return await arun(
            self._t, _Op("GET", f"skanyr/sites/{seg(site_id)}/timeline/{seg(snapshot_id)}")
        )

    async def diff(
        self,
        site_id: str,
        snapshot_a: Optional[str] = None,
        snapshot_b: Optional[str] = None,
    ) -> Dict[str, Any]:
        return await arun(
            self._t,
            _Op(
                "GET",
                f"skanyr/sites/{seg(site_id)}/diff",
                params=compact({"snapshot_a": snapshot_a, "snapshot_b": snapshot_b}),
            ),
        )

    async def get_graph(
        self,
        site_id: str,
        resource_type: Optional[str] = None,
        max_depth: Optional[int] = None,
        edge_kind: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Dict[str, Any]:
        return await arun(
            self._t,
            _Op(
                "GET",
                f"skanyr/sites/{seg(site_id)}/graph",
                params=compact(
                    {
                        "resource_type": resource_type,
                        "max_depth": max_depth,
                        "edge_kind": edge_kind,
                        "limit": limit,
                    }
                ),
            ),
        )

    async def get_graph_stats(self, site_id: str) -> Dict[str, Any]:
        return await arun(self._t, _Op("GET", f"skanyr/sites/{seg(site_id)}/graph/stats"))

    async def get_subgraph(
        self, site_id: str, resource_id: str, hops: Optional[int] = None
    ) -> Dict[str, Any]:
        return await arun(
            self._t,
            _Op(
                "GET",
                f"skanyr/sites/{seg(site_id)}/graph/subgraph/{seg(resource_id)}",
                params=compact({"hops": hops}),
            ),
        )

    async def list_resources(
        self,
        site_id: Optional[str] = None,
        resource_type: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        return await arun(
            self._t,
            _Op(
                "GET",
                "skanyr/resources",
                params=compact(
                    {
                        "site_id": site_id,
                        "resource_type": resource_type,
                        "limit": limit,
                        "offset": offset,
                    }
                ),
                parse=as_list,
            ),
        )

    async def get_resource(self, resource_id: str) -> Dict[str, Any]:
        return await arun(self._t, _Op("GET", f"skanyr/resources/{seg(resource_id)}"))

    async def search(
        self,
        query: str,
        site_id: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        mime_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Full-text search across the organisation's stored content."""
        return await arun(
            self._t,
            _Op(
                "POST",
                "skanyr/search",
                compact(
                    {
                        "query": query,
                        "site_id": site_id,
                        "limit": limit,
                        "offset": offset,
                        "mime_type": mime_type,
                    }
                ),
            ),
        )

    async def extract(
        self,
        content_hash: str,
        mime_type: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Extract text and structure from stored content (by its content hash)."""
        return await arun(
            self._t,
            _Op(
                "POST",
                "skanyr/extract",
                {
                    "content_hash": content_hash,
                    "mime_type": mime_type,
                    "metadata": metadata or {},
                },
            ),
        )

    async def get_extraction_text(self, content_hash: str) -> str:
        """The extracted plain text (the API answers text/plain)."""
        return await arun(
            self._t, _Op("GET", f"skanyr/extractions/{seg(content_hash)}/text", parse=_text)
        )

    async def get_extraction_structure(self, content_hash: str) -> Dict[str, Any]:
        return await arun(
            self._t, _Op("GET", f"skanyr/extractions/{seg(content_hash)}/structure")
        )
