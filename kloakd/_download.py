"""Streamed downloads: the crawl-extract and batch exports.

The export routes stream their rows as a file (JSON, NDJSON or CSV). The SDK
hands the body on as a stream, or writes it to a file, without holding it in
memory. An export is sent without a read timeout: the file is as long as the
job's results.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator, Iterator
from typing import Any

from kloakd.models import ExportCrawl, SavedExport

EXPORT_FORMATS = ("json", "ndjson", "csv")

_FILENAME = re.compile(r'filename="?([^";]+)"?')


def check_export_format(format: str) -> str:
    """``format`` if the API accepts it; ValueError otherwise (the API would
    answer 400)."""
    if format not in EXPORT_FORMATS:
        raise ValueError(
            f"format must be one of {', '.join(EXPORT_FORMATS)}, got {format!r}"
        )
    return format


def _filename(disposition: str | None) -> str | None:
    match = _FILENAME.search(disposition or "")
    return match.group(1) if match else None


def _header_bool(value: str | None) -> bool | None:
    """``true`` / ``false`` as the API writes a boolean header; None when
    the header is absent (or is neither)."""
    text = (value or "").strip().lower()
    if text == "true":
        return True
    if text == "false":
        return False
    return None


def _header_int(value: str | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def _export_crawl(headers: Any) -> ExportCrawl | None:
    """The ``X-Crawl-*`` headers of a crawl-extract export (kobe-scraper
    modules/webgrph/crawl_extract_router.py _crawl_headers). A value the
    crawl has not reported has no header; None when there is no
    ``X-Crawl-*`` header at all."""
    if not any(str(name).lower().startswith("x-crawl-") for name in headers):
        return None
    return ExportCrawl(
        status=headers.get("x-crawl-status"),
        is_partial=_header_bool(headers.get("x-crawl-partial")),
        partial_reason=headers.get("x-crawl-partial-reason"),
        pages_discovered=_header_int(headers.get("x-crawl-pages-discovered")),
        pages_fetched=_header_int(headers.get("x-crawl-pages-fetched")),
        pages_unfetched=_header_int(headers.get("x-crawl-pages-unfetched")),
        cancelled=_header_bool(headers.get("x-crawl-cancelled")),
        root_unfetched=_header_bool(headers.get("x-crawl-root-unfetched")),
    )


class _Export:
    """What an export's response headers say."""

    def __init__(self, response: Any, client: Any | None) -> None:
        self._response = response
        self._client = client
        #: The ``Content-Type`` header (``application/json``,
        #: ``application/x-ndjson`` or ``text/csv``).
        self.content_type: str | None = response.headers.get("content-type")
        #: The file name the API suggests (``Content-Disposition``).
        self.filename: str | None = _filename(
            response.headers.get("content-disposition")
        )
        #: The job's status when the export began (``X-Job-Status``). Set
        #: for crawl-extract exports, where a value other than ``completed``
        #: means the file holds the rows stored so far. None for batch
        #: exports, whose route sends no such header.
        self.job_status: str | None = response.headers.get("x-job-status")
        #: What the job's crawl did, from the ``X-Crawl-*`` headers. Set
        #: for crawl-extract exports; None when the response carries no
        #: ``X-Crawl-*`` header (a job with no crawl row, and every batch
        #: export). Each value is None when its header was not sent.
        self.crawl: ExportCrawl | None = _export_crawl(response.headers)

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(filename={self.filename!r}, "
            f"content_type={self.content_type!r}, job_status={self.job_status!r})"
        )


class ExportDownload(_Export):
    """An export's body as a stream. Use it as a context manager, or call
    ``close`` when done::

        with client.webgrph.export_crawl_extract(job_id, format="csv") as export:
            for chunk in export.iter_bytes():
                ...
    """

    def iter_bytes(self, chunk_size: int | None = None) -> Iterator[bytes]:
        """The body in chunks, as it arrives."""
        for chunk in self._response.iter_bytes(chunk_size):
            yield bytes(chunk)

    def read(self) -> bytes:
        """The whole body in memory (for a large job prefer ``iter_bytes``)."""
        return b"".join(self.iter_bytes())

    def close(self) -> None:
        self._response.close()
        if self._client is not None:
            self._client.close()

    def __enter__(self) -> ExportDownload:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class AsyncExportDownload(_Export):
    """Async equivalent of ExportDownload::

        async with await client.webgrph.export_crawl_extract(job_id) as export:
            async for chunk in export.aiter_bytes():
                ...
    """

    async def aiter_bytes(
        self, chunk_size: int | None = None
    ) -> AsyncIterator[bytes]:
        """The body in chunks, as it arrives."""
        async for chunk in self._response.aiter_bytes(chunk_size):
            yield bytes(chunk)

    async def aread(self) -> bytes:
        """The whole body in memory (for a large job prefer ``aiter_bytes``)."""
        return b"".join([chunk async for chunk in self.aiter_bytes()])

    async def aclose(self) -> None:
        await self._response.aclose()
        if self._client is not None:
            await self._client.aclose()

    async def __aenter__(self) -> AsyncExportDownload:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()


def _saved(export: _Export, path: str, size: int) -> SavedExport:
    return SavedExport(
        path=path,
        bytes=size,
        content_type=export.content_type,
        filename=export.filename,
        job_status=export.job_status,
        crawl=export.crawl,
    )


def save_export(export: ExportDownload, path: str) -> SavedExport:
    """Write an export to ``path`` as it arrives. The file is created once
    the API has answered 200, so a refused request leaves no file; a download
    that breaks part way raises and leaves the part written."""
    size = 0
    with export, open(path, "wb") as file:
        for chunk in export.iter_bytes():
            file.write(chunk)
            size += len(chunk)
    return _saved(export, path, size)


async def asave_export(export: AsyncExportDownload, path: str) -> SavedExport:
    """Async equivalent of save_export; each write runs in a worker thread."""
    size = 0
    async with export:
        with open(path, "wb") as file:
            async for chunk in export.aiter_bytes():
                await asyncio.to_thread(file.write, chunk)
                size += len(chunk)
    return _saved(export, path, size)
