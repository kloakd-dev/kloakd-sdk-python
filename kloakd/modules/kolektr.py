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

    # ── API Data ──────────────────────────────────────────────────────

    def get_api_data(self, api_endpoint: str) -> Dict[str, Any]:
        """Get all extracted data for a discovered API endpoint."""
        return self._t.get(f"kolektr/api-data/{api_endpoint}")

    def get_api_data_paginated(
        self, api_endpoint: str, offset: int = 0, limit: int = 1000
    ) -> Dict[str, Any]:
        """Get API data with pagination."""
        return self._t.get(
            f"kolektr/api-data/{api_endpoint}/paginated",
            params={"offset": offset, "limit": limit},
        )

    def extract_all_api_data(self, api_endpoint: str) -> Dict[str, Any]:
        """Extract all data from a discovered API endpoint."""
        return self._t.post(f"kolektr/api-data/{api_endpoint}/extract-all", {})

    # ── Content management ────────────────────────────────────────────

    def list_content(self) -> Dict[str, Any]:
        """List content items."""
        return self._t.get("kolektr/content")

    def get_content(self, item_id: str) -> Dict[str, Any]:
        """Get a content item by ID."""
        return self._t.get(f"kolektr/content/{item_id}")

    def delete_content(self, item_id: str) -> None:
        """Delete a content item."""
        self._t.delete(f"kolektr/content/{item_id}")

    # ── Job management ────────────────────────────────────────────────

    def list_jobs(self) -> Dict[str, Any]:
        """List extraction jobs."""
        return self._t.get("kolektr/jobs")

    def create_job(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Create an extraction job."""
        return self._t.post("kolektr/jobs", config)

    def get_job(self, job_id: str) -> Dict[str, Any]:
        """Get an extraction job by ID."""
        return self._t.get(f"kolektr/jobs/{job_id}")

    def get_job_status(self, job_id: str) -> Dict[str, Any]:
        """Get extraction job status."""
        return self._t.get(f"kolektr/extraction-jobs/{job_id}/status")

    def get_job_progress(self, job_id: str) -> Dict[str, Any]:
        """Get job progress."""
        return self._t.get(f"kolektr/jobs/{job_id}/progress")

    def get_job_progress_events(self, job_id: str) -> Dict[str, Any]:
        """Get job progress events."""
        return self._t.get(f"kolektr/jobs/{job_id}/progress/events")

    def get_job_progress_latest(self, job_id: str) -> Dict[str, Any]:
        """Get latest progress event for a job."""
        return self._t.get(f"kolektr/jobs/{job_id}/progress/latest")

    def get_job_progress_summary(self, job_id: str) -> Dict[str, Any]:
        """Get job progress summary."""
        return self._t.get(f"kolektr/jobs/{job_id}/progress/summary")

    # ── Pipeline ──────────────────────────────────────────────────────

    def get_pipeline_events(self, pipeline_id: str) -> Dict[str, Any]:
        """Get events for a pipeline run."""
        return self._t.get(f"kolektr/pipeline/{pipeline_id}/events")

    def get_pipeline_stream(self, pipeline_id: str) -> Dict[str, Any]:
        """Stream pipeline data."""
        return self._t.get(f"kolektr/pipeline/{pipeline_id}/stream")

    # ── Progress tracking ─────────────────────────────────────────────

    def list_progress_phases(self) -> Dict[str, Any]:
        """List all progress phases."""
        return self._t.get("kolektr/progress/phases")

    def get_progress_phase(self, phase_name: str) -> Dict[str, Any]:
        """Get info for a specific progress phase."""
        return self._t.get(f"kolektr/progress/phases/{phase_name}")

    def get_progress_phase_steps(self, phase_name: str) -> Dict[str, Any]:
        """Get steps for a progress phase."""
        return self._t.get(f"kolektr/progress/phases/{phase_name}/steps")

    def get_progress_summary(self) -> Dict[str, Any]:
        """Get overall progress summary."""
        return self._t.get("kolektr/progress/summary")

    # ── Scraper config ────────────────────────────────────────────────

    def list_scrapers(self) -> Dict[str, Any]:
        """List scraper configurations."""
        return self._t.get("kolektr/scrapers")

    def create_scraper(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Create a scraper configuration."""
        return self._t.post("kolektr/scrapers", config)

    def get_scraper(self, scraper_id: str) -> Dict[str, Any]:
        """Get a scraper configuration by ID."""
        return self._t.get(f"kolektr/scrapers/{scraper_id}")

    def update_scraper(self, scraper_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        """Update a scraper configuration."""
        return self._t.patch(f"kolektr/scrapers/{scraper_id}", updates)

    def delete_scraper(self, scraper_id: str) -> None:
        """Delete a scraper configuration."""
        self._t.delete(f"kolektr/scrapers/{scraper_id}")


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

    async def get_api_data(self, api_endpoint: str) -> Dict[str, Any]:
        """Async equivalent of KolektrNamespace.get_api_data."""
        return await self._t.get(f"kolektr/api-data/{api_endpoint}")

    async def get_api_data_paginated(
        self, api_endpoint: str, offset: int = 0, limit: int = 1000
    ) -> Dict[str, Any]:
        """Async equivalent of KolektrNamespace.get_api_data_paginated."""
        return await self._t.get(
            f"kolektr/api-data/{api_endpoint}/paginated",
            params={"offset": offset, "limit": limit},
        )

    async def extract_all_api_data(self, api_endpoint: str) -> Dict[str, Any]:
        """Async equivalent of KolektrNamespace.extract_all_api_data."""
        return await self._t.post(f"kolektr/api-data/{api_endpoint}/extract-all", {})

    async def list_content(self) -> Dict[str, Any]:
        """Async equivalent of KolektrNamespace.list_content."""
        return await self._t.get("kolektr/content")

    async def get_content(self, item_id: str) -> Dict[str, Any]:
        """Async equivalent of KolektrNamespace.get_content."""
        return await self._t.get(f"kolektr/content/{item_id}")

    async def delete_content(self, item_id: str) -> None:
        """Async equivalent of KolektrNamespace.delete_content."""
        await self._t.delete(f"kolektr/content/{item_id}")

    async def list_jobs(self) -> Dict[str, Any]:
        """Async equivalent of KolektrNamespace.list_jobs."""
        return await self._t.get("kolektr/jobs")

    async def create_job(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Async equivalent of KolektrNamespace.create_job."""
        return await self._t.post("kolektr/jobs", config)

    async def get_job(self, job_id: str) -> Dict[str, Any]:
        """Async equivalent of KolektrNamespace.get_job."""
        return await self._t.get(f"kolektr/jobs/{job_id}")

    async def get_job_status(self, job_id: str) -> Dict[str, Any]:
        """Async equivalent of KolektrNamespace.get_job_status."""
        return await self._t.get(f"kolektr/extraction-jobs/{job_id}/status")

    async def get_job_progress(self, job_id: str) -> Dict[str, Any]:
        """Async equivalent of KolektrNamespace.get_job_progress."""
        return await self._t.get(f"kolektr/jobs/{job_id}/progress")

    async def get_job_progress_events(self, job_id: str) -> Dict[str, Any]:
        """Async equivalent of KolektrNamespace.get_job_progress_events."""
        return await self._t.get(f"kolektr/jobs/{job_id}/progress/events")

    async def get_job_progress_latest(self, job_id: str) -> Dict[str, Any]:
        """Async equivalent of KolektrNamespace.get_job_progress_latest."""
        return await self._t.get(f"kolektr/jobs/{job_id}/progress/latest")

    async def get_job_progress_summary(self, job_id: str) -> Dict[str, Any]:
        """Async equivalent of KolektrNamespace.get_job_progress_summary."""
        return await self._t.get(f"kolektr/jobs/{job_id}/progress/summary")

    async def get_pipeline_events(self, pipeline_id: str) -> Dict[str, Any]:
        """Async equivalent of KolektrNamespace.get_pipeline_events."""
        return await self._t.get(f"kolektr/pipeline/{pipeline_id}/events")

    async def get_pipeline_stream(self, pipeline_id: str) -> Dict[str, Any]:
        """Async equivalent of KolektrNamespace.get_pipeline_stream."""
        return await self._t.get(f"kolektr/pipeline/{pipeline_id}/stream")

    async def list_progress_phases(self) -> Dict[str, Any]:
        """Async equivalent of KolektrNamespace.list_progress_phases."""
        return await self._t.get("kolektr/progress/phases")

    async def get_progress_phase(self, phase_name: str) -> Dict[str, Any]:
        """Async equivalent of KolektrNamespace.get_progress_phase."""
        return await self._t.get(f"kolektr/progress/phases/{phase_name}")

    async def get_progress_phase_steps(self, phase_name: str) -> Dict[str, Any]:
        """Async equivalent of KolektrNamespace.get_progress_phase_steps."""
        return await self._t.get(f"kolektr/progress/phases/{phase_name}/steps")

    async def get_progress_summary(self) -> Dict[str, Any]:
        """Async equivalent of KolektrNamespace.get_progress_summary."""
        return await self._t.get("kolektr/progress/summary")

    async def list_scrapers(self) -> Dict[str, Any]:
        """Async equivalent of KolektrNamespace.list_scrapers."""
        return await self._t.get("kolektr/scrapers")

    async def create_scraper(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Async equivalent of KolektrNamespace.create_scraper."""
        return await self._t.post("kolektr/scrapers", config)

    async def get_scraper(self, scraper_id: str) -> Dict[str, Any]:
        """Async equivalent of KolektrNamespace.get_scraper."""
        return await self._t.get(f"kolektr/scrapers/{scraper_id}")

    async def update_scraper(self, scraper_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        """Async equivalent of KolektrNamespace.update_scraper."""
        return await self._t.patch(f"kolektr/scrapers/{scraper_id}", updates)

    async def delete_scraper(self, scraper_id: str) -> None:
        """Async equivalent of KolektrNamespace.delete_scraper."""
        await self._t.delete(f"kolektr/scrapers/{scraper_id}")
