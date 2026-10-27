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
        fetch_artifact_id=fetch.artifact_id,
    )
    for record in data.records[:3]:
        print(record)

Documentation: https://docs.kloakd.dev/sdk/python
"""

from kloakd._client import AsyncKloakd, Kloakd
from kloakd.errors import (
    ApiError,
    AuthenticationError,
    BillingUnavailableError,
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
    CrawlEvent,
    CrawlPage,
    CrawlProgressEvent,
    CrawlResult,
    DuplicateCheckResult,
    ExtractionResult,
    FetchEvent,
    FetchResult,
    FormDetectionResult,
    MfaChallenge,
    MfaDetectionResult,
    NexusAnalyzeResult,
    NexusExecuteResult,
    NexusKnowledgeResult,
    NexusSynthesisResult,
    NexusVerifyResult,
    PageNode,
    ParseResult,
    SessionResult,
    SiteCrawlResult,
    WorkflowExecutionResult,
    WorkflowResult,
)

__version__ = "0.3.0"
__all__ = [
    # Clients
    "Kloakd",
    "AsyncKloakd",
    # Errors
    "KloakdError",
    "AuthenticationError",
    "NotEntitledError",
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
    "CrawlEvent",
    "PageNode",
    # Crawl orchestrator models
    "CrawlPage",
    "SiteCrawlResult",
    "CrawlProgressEvent",
    # Nexus models
    "NexusAnalyzeResult",
    "NexusSynthesisResult",
    "NexusVerifyResult",
    "NexusExecuteResult",
    "NexusKnowledgeResult",
    # Parlyr models
    "ParseResult",
    "ChatEvent",
    "ChatTurn",
    # Fetchyr models
    "SessionResult",
    "WorkflowResult",
    "WorkflowExecutionResult",
    "FormDetectionResult",
    "MfaDetectionResult",
    "MfaChallenge",
    "DuplicateCheckResult",
    # Kolektr models
    "ExtractionResult",
]
