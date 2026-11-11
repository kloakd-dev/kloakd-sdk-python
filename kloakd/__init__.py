"""
KLOAKD Python SDK — Official client library for the KLOAKD API.

Quickstart::

    from kloakd import Kloakd

    client = Kloakd(
        api_key="sk-live-...",
        organization_id="your-org-id",
    )

    # Fetch with anti-bot bypass
    fetch = client.evadr.fetch("https://books.toscrape.com")

    # Extract — reuse the fetch artifact, no double-fetch
    data = client.kolektr.page(
        "https://books.toscrape.com",
        schema={"title": "css:h3 a", "price": "css:p.price_color"},
        item_selector="article.product_pod",  # one record per book
        fetch_artifact_id=fetch.artifact_id,
    )
    for record in data.records[:3]:
        print(record)

Requests that run long (fetch, extract, the Fetchyr form and login calls,
Nexus analyze/synthesize) may be handed off by the API as a job
(HTTP 202, after about 85 s); the SDK follows it and returns the same result.
A request whose wait ran out raises JobTimeoutError; resume it with
``client.wait_for_handoff(e.job_id)``.

Documentation: https://docs.kloakd.dev/sdk/python
"""

from kloakd._client import AsyncKloakd, Kloakd
from kloakd._download import AsyncExportDownload, ExportDownload
from kloakd.errors import (
    ApiError,
    AuthenticationError,
    BillingUnavailableError,
    ConcurrencyLimitError,
    ForbiddenError,
    JobFailedError,
    JobTimeoutError,
    KloakdError,
    NotEntitledError,
    PaymentRequiredError,
    QuotaExceededError,
    RateLimitError,
    UpstreamError,
)
from kloakd.models import (
    AnalyzeResult,
    ChatEvent,
    ChatTurn,
    CrawlContinueResult,
    CrawlEvent,
    CrawlExtractCancelResult,
    CrawlExtractCrawl,
    CrawlExtractJob,
    CrawlExtractPage,
    CrawlExtractPagesResult,
    CrawlExtractResultsPage,
    CrawlExtractRow,
    CrawlExtractStatus,
    CrawlPage,
    CrawlProgressEvent,
    CrawlResult,
    DuplicateCheckResult,
    ExportCrawl,
    ExtractionResult,
    FetchEvent,
    FetchResult,
    FormDetectionResult,
    LoginSession,
    MfaChallenge,
    MfaDetectionResult,
    NexusAnalyzeResult,
    NexusSafetyCheck,
    NexusSynthesisResult,
    NexusVerifyResult,
    PageNode,
    ParseResult,
    SavedExport,
    SchemaField,
    SchemaSpec,
    SessionResult,
    SessionStatus,
    SiteCrawlResult,
    WorkflowExecutionResult,
    WorkflowResult,
)
from kloakd.modules.kolektr import schema_spec

__version__ = "0.6.0"
__all__ = [
    # Clients
    "Kloakd",
    "AsyncKloakd",
    # Errors
    "KloakdError",
    "AuthenticationError",
    "NotEntitledError",
    "ForbiddenError",
    "ConcurrencyLimitError",
    "RateLimitError",
    "UpstreamError",
    "ApiError",
    "PaymentRequiredError",
    "QuotaExceededError",
    "BillingUnavailableError",
    "JobFailedError",
    "JobTimeoutError",
    # Evadr models
    "FetchResult",
    "FetchEvent",
    "AnalyzeResult",
    # Webgrph models
    "CrawlResult",
    "CrawlContinueResult",
    "CrawlEvent",
    "PageNode",
    "CrawlExtractJob",
    "CrawlExtractStatus",
    "CrawlExtractCrawl",
    "CrawlExtractRow",
    "CrawlExtractResultsPage",
    "CrawlExtractPage",
    "CrawlExtractPagesResult",
    "CrawlExtractCancelResult",
    # Exports (crawl-extract and batch jobs)
    "ExportDownload",
    "AsyncExportDownload",
    "SavedExport",
    "ExportCrawl",
    # Crawl orchestrator models
    "CrawlPage",
    "SiteCrawlResult",
    "CrawlProgressEvent",
    # Nexus models
    "NexusAnalyzeResult",
    "NexusSynthesisResult",
    "NexusVerifyResult",
    "NexusSafetyCheck",
    # Parlyr models
    "ParseResult",
    "ChatEvent",
    "ChatTurn",
    # Fetchyr models
    "SessionResult",
    "LoginSession",
    "SessionStatus",
    "WorkflowResult",
    "WorkflowExecutionResult",
    "FormDetectionResult",
    "MfaDetectionResult",
    "MfaChallenge",
    "DuplicateCheckResult",
    # Kolektr models
    "ExtractionResult",
    "SchemaField",
    "SchemaSpec",
    "schema_spec",
]
