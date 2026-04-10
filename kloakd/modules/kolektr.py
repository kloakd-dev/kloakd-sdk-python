"""
KLOAKD SDK — Kolektr module namespace.

Kolektr is KLOAKD's Data Extraction layer — the culmination of the pipeline.
It accepts artifacts from Evadr (FETCHED_CONTENT), Fetchyr (AUTHENTICATED_SESSION),
and Skanyr (API_MAP) to skip redundant work.

Usage::

    # Simple extraction with CSS schema
    result = client.kolektr.page(
        "https://books.toscrape.com",
        schema={"title": "css:h3 a", "price": "css:p.price_color"},
    )

    # Reuse Evadr artifact — no double-fetch
    fetch = client.evadr.fetch("https://protected.example.com")
    result = client.kolektr.page(
        "https://protected.example.com",
        fetch_artifact_id=fetch.artifact_id,
    )
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional

from kloakd.models import ExtractionResult

if TYPE_CHECKING:
    from kloakd._http import _AsyncHttpTransport, _HttpTransport


def _build_schema_spec(schema: Dict[str, str]) -> Dict[str, Any]:
    """Convert simple CSS selector dict to API schema_spec format."""
    return {
        "fields": [
            {"name": k, "selector": v.replace("css:", "")}
            for k, v in schema.items()
        ]
    }


def _parse_extraction(raw: Dict[str, Any], url: str) -> ExtractionResult:
    artifact = raw.get("artifact")
    return ExtractionResult(
        success=raw.get("success", False),
        url=raw.get("url", url),
        method=raw.get("method", ""),
        records=raw.get("records", []),
        total_records=raw.get("total_records", 0),
        pages_scraped=raw.get("pages_scraped", 0),
        artifact_id=artifact.get("artifact_id") if artifact else raw.get("artifact_id"),
        job_id=raw.get("job_id"),
        has_more=raw.get("has_more", False),
        total=raw.get("total", raw.get("total_records", 0)),
        error=raw.get("error"),
    )


class KolektrNamespace:
    """Synchronous Kolektr operations. Access via ``client.kolektr``."""

    def __init__(self, transport: "_HttpTransport") -> None:
        self._t = transport

    def page(
        self,
        url: str,
        schema: Optional[Dict[str, str]] = None,
        fetch_artifact_id: Optional[str] = None,
        session_artifact_id: Optional[str] = None,
        api_map_artifact_id: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> ExtractionResult:
        """
        Extract structured data from a URL.

        Artifacts from prior module calls eliminate redundant work:
        - fetch_artifact_id  → skip re-fetch (from Evadr)
        - session_artifact_id → use authenticated browser (from Fetchyr)
        - api_map_artifact_id → use API endpoints (from Skanyr)

        Schema format::

            schema = {
                "title": "css:h1.product-name",
                "price": "css:span.price",
            }

        Args:
            url: Target URL.
            schema: CSS selector schema dict.
            fetch_artifact_id: FETCHED_CONTENT artifact from Evadr.
            session_artifact_id: AUTHENTICATED_SESSION artifact from Fetchyr.
            api_map_artifact_id: API_MAP artifact from Skanyr.
            options: Additional extraction options.
            limit: Max records in this response.
            offset: Pagination offset.

        Returns:
            ExtractionResult with records, total_records, and artifact_id.
        """
        body: Dict[str, Any] = {"url": url, "limit": limit, "offset": offset}
        if schema:
            body["schema_spec"] = _build_schema_spec(schema)
        if fetch_artifact_id:
            body["fetch_artifact_id"] = fetch_artifact_id
        if session_artifact_id:
            body["session_artifact_id"] = session_artifact_id
        if api_map_artifact_id:
            body["api_map_artifact_id"] = api_map_artifact_id
        if options:
            body["options"] = options

        raw = self._t.post("kolektr/extract", body)
        return _parse_extraction(raw, url)

    def page_all(
        self,
        url: str,
        schema: Optional[Dict[str, str]] = None,
        fetch_artifact_id: Optional[str] = None,
        session_artifact_id: Optional[str] = None,
        api_map_artifact_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Auto-paginate extraction, returning all records.

        Returns:
            Complete list of extracted record dicts.
        """
        all_records: List[Dict[str, Any]] = []
        offset = 0
        while True:
            result = self.page(
                url,
                schema=schema,
                fetch_artifact_id=fetch_artifact_id,
                session_artifact_id=session_artifact_id,
                api_map_artifact_id=api_map_artifact_id,
                limit=100,
                offset=offset,
            )
            all_records.extend(result.records)
            if not result.has_more:
                break
            offset += len(result.records)
        return all_records

    def extract_html(
        self,
        html: str,
        url: str,
        schema: Optional[Dict[str, str]] = None,
    ) -> ExtractionResult:
        """
        Extract structured data from raw HTML (in-process, no HTTP fetch).

        Args:
            html: Raw HTML string.
            url: Source URL (for metadata only).
            schema: CSS selector schema dict.

        Returns:
            ExtractionResult with records.
        """
        body: Dict[str, Any] = {"html": html, "url": url}
        if schema:
            body["schema_spec"] = _build_schema_spec(schema)

        raw = self._t.post("kolektr/extract/html", body)
        return _parse_extraction(raw, url)


class AsyncKolektrNamespace:
    """Async Kolektr operations. Access via ``async_client.kolektr``."""

    def __init__(self, transport: "_AsyncHttpTransport") -> None:
        self._t = transport

    async def page(
        self,
        url: str,
        schema: Optional[Dict[str, str]] = None,
        fetch_artifact_id: Optional[str] = None,
        session_artifact_id: Optional[str] = None,
        api_map_artifact_id: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> ExtractionResult:
        """Async equivalent of KolektrNamespace.page."""
        body: Dict[str, Any] = {"url": url, "limit": limit, "offset": offset}
        if schema:
            body["schema_spec"] = _build_schema_spec(schema)
        if fetch_artifact_id:
            body["fetch_artifact_id"] = fetch_artifact_id
        if session_artifact_id:
            body["session_artifact_id"] = session_artifact_id
        if api_map_artifact_id:
            body["api_map_artifact_id"] = api_map_artifact_id
        if options:
            body["options"] = options

        raw = await self._t.post("kolektr/extract", body)
        return _parse_extraction(raw, url)

    async def extract_html(
        self,
        html: str,
        url: str,
        schema: Optional[Dict[str, str]] = None,
    ) -> ExtractionResult:
        """Async equivalent of KolektrNamespace.extract_html."""
        body: Dict[str, Any] = {"html": html, "url": url}
        if schema:
            body["schema_spec"] = _build_schema_spec(schema)

        raw = await self._t.post("kolektr/extract/html", body)
        return _parse_extraction(raw, url)
