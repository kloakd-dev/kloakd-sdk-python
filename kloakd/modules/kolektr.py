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

An extraction still running after about 85 s is handed off as a job
(HTTP 202); ``page`` follows it to the same result.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

from kloakd.models import ExtractionResult
from kloakd.modules._ops import as_dict, compact, seg

if TYPE_CHECKING:
    from kloakd._http import _AsyncHttpTransport, _HttpTransport


def _selector(value: str) -> str:
    """A shorthand selector without its optional ``css:`` prefix."""
    return value[4:].strip() if value.startswith("css:") else value


def _build_schema_spec(schema: Any) -> Dict[str, Any]:
    """The API's ``schema_spec`` (modules/kolektr/router.py SchemaSpec):

    - a full spec (a dict with a ``fields`` list) is sent as given;
    - a list of fields ``[{"name", "selector", ...}]`` becomes ``{"fields": [...]}``;
    - the shorthand ``{field: "css:selector"}`` (prefix optional) is
      converted to ``{"fields": [{"name": field, "selector": selector}]}``.
    """
    if isinstance(schema, list):
        return {"fields": list(schema)}
    if isinstance(schema.get("fields"), list):
        return dict(schema)
    return {
        "fields": [
            {"name": k, "selector": _selector(v)}
            if isinstance(v, str)
            else {"name": k, **v}
            for k, v in schema.items()
        ]
    }


def _api_data_path(api_endpoint: str, suffix: str = "") -> str:
    """``kolektr/api-data/{api_endpoint:path}``: the endpoint URL is sent as
    one encoded segment, as the app does with encodeURIComponent."""
    return f"kolektr/api-data/{seg(api_endpoint)}{suffix}"


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
        auth_required=bool(raw.get("auth_required", False)),
        discovery_id=raw.get("discovery_id"),
    )


class KolektrNamespace:
    """Synchronous Kolektr operations. Access via ``client.kolektr``."""

    def __init__(self, transport: "_HttpTransport") -> None:
        self._t = transport

    def page(
        self,
        url: str,
        schema: Optional[Union[Dict[str, Any], List[Dict[str, Any]]]] = None,
        fetch_artifact_id: Optional[str] = None,
        session_artifact_id: Optional[str] = None,
        api_map_artifact_id: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
        level: Optional[str] = None,
    ) -> ExtractionResult:
        """
        Extract structured data from a URL.

        Artifacts from prior module calls eliminate redundant work:
        - fetch_artifact_id  → skip re-fetch (from Evadr)
        - session_artifact_id → use authenticated browser (from Fetchyr)
        - api_map_artifact_id → use API endpoints (from Skanyr)

        Schema format: the shorthand (``css:`` prefix optional)::

            schema = {
                "title": "css:h1.product-name",
                "price": "span.price",
            }

        or a list of fields ``[{"name": "title", "selector": "h1",
        "attribute": None, "type": "text"}]``, or a full ``schema_spec``
        dict with ``fields`` (and ``pagination``, ``max_pages``,
        ``output_format``).

        Args:
            url: Target URL.
            schema: Shorthand dict, list of fields, or full schema_spec.
            fetch_artifact_id: FETCHED_CONTENT artifact from Evadr.
            session_artifact_id: AUTHENTICATED_SESSION artifact from Fetchyr.
            api_map_artifact_id: API_MAP artifact from Skanyr.
            options: Additional extraction options.
            level: Extraction level to force (the API chooses when omitted).

        Returns:
            ExtractionResult with records, total_records, and artifact_id.
        """
        body: Dict[str, Any] = {"url": url}
        if level:
            body["level"] = level
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

        raw = self._t.post_following("kolektr/extract", body)
        return _parse_extraction(raw, url)

    def page_all(
        self,
        url: str,
        schema: Optional[Union[Dict[str, Any], List[Dict[str, Any]]]] = None,
        fetch_artifact_id: Optional[str] = None,
        session_artifact_id: Optional[str] = None,
        api_map_artifact_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """All records of a page's extraction (the API returns them in one response)."""
        return self.page(
            url,
            schema=schema,
            fetch_artifact_id=fetch_artifact_id,
            session_artifact_id=session_artifact_id,
            api_map_artifact_id=api_map_artifact_id,
        ).records

    def extract_html(
        self,
        html: str,
        url: str,
        schema: Optional[Union[Dict[str, Any], List[Dict[str, Any]]]] = None,
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

    # ── API Data ──────────────────────────────────────────────────────

    def get_api_data(
        self, api_endpoint: str, endpoint_hash: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get all extracted data for a discovered API endpoint."""
        return as_dict(self._t.get(
            _api_data_path(api_endpoint), params=compact({"endpoint_hash": endpoint_hash})
        ))

    def get_api_data_paginated(
        self,
        api_endpoint: str,
        offset: int = 0,
        limit: int = 1000,
        endpoint_hash: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get API data with pagination."""
        return as_dict(self._t.get(
            _api_data_path(api_endpoint, "/paginated"),
            params=compact(
                {"offset": offset, "limit": limit, "endpoint_hash": endpoint_hash}
            ),
        ))

    def extract_all_api_data(
        self,
        api_endpoint: str,
        endpoint_hash: Optional[str] = None,
        max_records: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Extract all data from a discovered API endpoint."""
        return as_dict(self._t.request(
            "POST",
            _api_data_path(api_endpoint, "/extract-all"),
            json_body={},
            params=compact(
                {"endpoint_hash": endpoint_hash, "max_records": max_records}
            ),
        ))

    # ── Content management ────────────────────────────────────────────

    def list_content(
        self,
        page: Optional[int] = None,
        page_size: Optional[int] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List content items."""
        return as_dict(self._t.get(
            "kolektr/content",
            params=compact({"page": page, "page_size": page_size, "search": search}),
        ))

    def get_content(self, item_id: str) -> Dict[str, Any]:
        """Get a content item by ID."""
        return as_dict(self._t.get(f"kolektr/content/{seg(item_id)}"))

    def delete_content(self, item_id: str) -> None:
        """Delete a content item."""
        self._t.delete(f"kolektr/content/{seg(item_id)}")

    # ── Job management ────────────────────────────────────────────────

    def list_jobs(
        self,
        page: Optional[int] = None,
        limit: Optional[int] = None,
        status_filter: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List extraction jobs."""
        return as_dict(self._t.get(
            "kolektr/jobs",
            params=compact(
                {"page": page, "limit": limit, "status_filter": status_filter}
            ),
        ))

    def get_job(self, job_id: str) -> Dict[str, Any]:
        """Get an extraction job by ID."""
        return as_dict(self._t.get(f"kolektr/jobs/{seg(job_id)}"))

    def get_job_status(self, job_id: str) -> Dict[str, Any]:
        """Get extraction job status."""
        return as_dict(self._t.get(f"kolektr/extraction-jobs/{seg(job_id)}/status"))

    # ── Scraper config ────────────────────────────────────────────────

    def list_scrapers(
        self,
        page: Optional[int] = None,
        page_size: Optional[int] = None,
        is_template: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """List scraper configurations."""
        return as_dict(self._t.get(
            "kolektr/scrapers",
            params=compact(
                {"page": page, "page_size": page_size, "is_template": is_template}
            ),
        ))

    def create_scraper(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Create a scraper configuration."""
        return as_dict(self._t.post("kolektr/scrapers", config))

    def get_scraper(self, scraper_id: str) -> Dict[str, Any]:
        """Get a scraper configuration by ID."""
        return as_dict(self._t.get(f"kolektr/scrapers/{seg(scraper_id)}"))

    def update_scraper(self, scraper_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        """Update a scraper configuration."""
        return as_dict(self._t.patch(f"kolektr/scrapers/{seg(scraper_id)}", updates))

    def delete_scraper(self, scraper_id: str) -> None:
        """Delete a scraper configuration."""
        self._t.delete(f"kolektr/scrapers/{seg(scraper_id)}")


class AsyncKolektrNamespace:
    """Async Kolektr operations. Access via ``async_client.kolektr``."""

    def __init__(self, transport: "_AsyncHttpTransport") -> None:
        self._t = transport

    async def page(
        self,
        url: str,
        schema: Optional[Union[Dict[str, Any], List[Dict[str, Any]]]] = None,
        fetch_artifact_id: Optional[str] = None,
        session_artifact_id: Optional[str] = None,
        api_map_artifact_id: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
        level: Optional[str] = None,
    ) -> ExtractionResult:
        """Async equivalent of KolektrNamespace.page."""
        body: Dict[str, Any] = {"url": url}
        if level:
            body["level"] = level
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

        raw = await self._t.post_following("kolektr/extract", body)
        return _parse_extraction(raw, url)

    async def page_all(
        self,
        url: str,
        schema: Optional[Union[Dict[str, Any], List[Dict[str, Any]]]] = None,
        fetch_artifact_id: Optional[str] = None,
        session_artifact_id: Optional[str] = None,
        api_map_artifact_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Async equivalent of KolektrNamespace.page_all."""
        result = await self.page(
            url,
            schema=schema,
            fetch_artifact_id=fetch_artifact_id,
            session_artifact_id=session_artifact_id,
            api_map_artifact_id=api_map_artifact_id,
        )
        return result.records

    async def extract_html(
        self,
        html: str,
        url: str,
        schema: Optional[Union[Dict[str, Any], List[Dict[str, Any]]]] = None,
    ) -> ExtractionResult:
        """Async equivalent of KolektrNamespace.extract_html."""
        body: Dict[str, Any] = {"html": html, "url": url}
        if schema:
            body["schema_spec"] = _build_schema_spec(schema)

        raw = await self._t.post("kolektr/extract/html", body)
        return _parse_extraction(raw, url)

    async def get_api_data(
        self, api_endpoint: str, endpoint_hash: Optional[str] = None
    ) -> Dict[str, Any]:
        """Async equivalent of KolektrNamespace.get_api_data."""
        return as_dict(await self._t.get(
            _api_data_path(api_endpoint), params=compact({"endpoint_hash": endpoint_hash})
        ))

    async def get_api_data_paginated(
        self,
        api_endpoint: str,
        offset: int = 0,
        limit: int = 1000,
        endpoint_hash: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Async equivalent of KolektrNamespace.get_api_data_paginated."""
        return as_dict(await self._t.get(
            _api_data_path(api_endpoint, "/paginated"),
            params=compact(
                {"offset": offset, "limit": limit, "endpoint_hash": endpoint_hash}
            ),
        ))

    async def extract_all_api_data(
        self,
        api_endpoint: str,
        endpoint_hash: Optional[str] = None,
        max_records: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Async equivalent of KolektrNamespace.extract_all_api_data."""
        return as_dict(await self._t.request(
            "POST",
            _api_data_path(api_endpoint, "/extract-all"),
            json_body={},
            params=compact(
                {"endpoint_hash": endpoint_hash, "max_records": max_records}
            ),
        ))

    async def list_content(
        self,
        page: Optional[int] = None,
        page_size: Optional[int] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Async equivalent of KolektrNamespace.list_content."""
        return as_dict(await self._t.get(
            "kolektr/content",
            params=compact({"page": page, "page_size": page_size, "search": search}),
        ))

    async def get_content(self, item_id: str) -> Dict[str, Any]:
        """Async equivalent of KolektrNamespace.get_content."""
        return as_dict(await self._t.get(f"kolektr/content/{seg(item_id)}"))

    async def delete_content(self, item_id: str) -> None:
        """Async equivalent of KolektrNamespace.delete_content."""
        await self._t.delete(f"kolektr/content/{seg(item_id)}")

    async def list_jobs(
        self,
        page: Optional[int] = None,
        limit: Optional[int] = None,
        status_filter: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Async equivalent of KolektrNamespace.list_jobs."""
        return as_dict(await self._t.get(
            "kolektr/jobs",
            params=compact(
                {"page": page, "limit": limit, "status_filter": status_filter}
            ),
        ))

    async def get_job(self, job_id: str) -> Dict[str, Any]:
        """Async equivalent of KolektrNamespace.get_job."""
        return as_dict(await self._t.get(f"kolektr/jobs/{seg(job_id)}"))

    async def get_job_status(self, job_id: str) -> Dict[str, Any]:
        """Async equivalent of KolektrNamespace.get_job_status."""
        return as_dict(await self._t.get(f"kolektr/extraction-jobs/{seg(job_id)}/status"))

    async def list_scrapers(
        self,
        page: Optional[int] = None,
        page_size: Optional[int] = None,
        is_template: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Async equivalent of KolektrNamespace.list_scrapers."""
        return as_dict(await self._t.get(
            "kolektr/scrapers",
            params=compact(
                {"page": page, "page_size": page_size, "is_template": is_template}
            ),
        ))

    async def create_scraper(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Async equivalent of KolektrNamespace.create_scraper."""
        return as_dict(await self._t.post("kolektr/scrapers", config))

    async def get_scraper(self, scraper_id: str) -> Dict[str, Any]:
        """Async equivalent of KolektrNamespace.get_scraper."""
        return as_dict(await self._t.get(f"kolektr/scrapers/{seg(scraper_id)}"))

    async def update_scraper(self, scraper_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        """Async equivalent of KolektrNamespace.update_scraper."""
        return as_dict(await self._t.patch(f"kolektr/scrapers/{seg(scraper_id)}", updates))

    async def delete_scraper(self, scraper_id: str) -> None:
        """Async equivalent of KolektrNamespace.delete_scraper."""
        await self._t.delete(f"kolektr/scrapers/{seg(scraper_id)}")
