"""
KLOAKD SDK — Result models.

All models are plain dataclasses with no framework coupling.
They are the return types of every namespace method and can be
serialised to dict via dataclasses.asdict() or inspected directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TypedDict, Union

# ---------------------------------------------------------------------------
# Evadr — Anti-Bot Intelligence
# ---------------------------------------------------------------------------


@dataclass
class FetchResult:
    """Result of an Evadr fetch operation.

    ``html`` is None when the API sent none, for example when the target is
    a login page (``auth_required``); then ``discovery_id`` names the
    auth-chain discovery (``fetchyr.get_auth_chain_status``)."""

    success: bool
    url: str
    status_code: int
    tier_used: int
    html: Optional[str] = None
    vendor_detected: Optional[str] = None
    anti_bot_bypassed: bool = False
    artifact_id: Optional[str] = None
    error: Optional[str] = None
    #: True when a login page was detected at the target URL.
    auth_required: bool = False
    #: The auth-chain discovery id when ``auth_required`` is true.
    discovery_id: Optional[str] = None

    @property
    def ok(self) -> bool:
        """True when the fetch succeeded with no error."""
        return self.success and self.error is None


@dataclass
class FetchEvent:
    """A single server-sent event from an Evadr fetch job's stream.

    The API sends pipeline events (``type`` is ``pipeline_step``,
    ``pipeline_error`` or ``pipeline_complete``, with ``stage_id``,
    ``status``, ``message``, ``progress_pct``, ``metadata``, ``error`` and
    ``sequence``; kobe-scraper core/pipeline/models.py PipelineEvent), or,
    when it cannot subscribe to them, job-state events (``type`` is
    ``STATUS``, ``COMPLETE``, ``FAILED`` or ``ERROR``, with ``status``,
    ``tier_used``, ``artifact_id`` and ``error``; modules/evadr/router.py).
    """

    type: str
    stage_id: Optional[str] = None
    status: Optional[str] = None
    message: Optional[str] = None
    progress_pct: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    #: A pipeline error object, or a job-state event's error string.
    error: Optional[Union[str, Dict[str, Any]]] = None
    sequence: Optional[int] = None
    job_id: Optional[str] = None
    tier_used: Optional[int] = None
    artifact_id: Optional[str] = None


@dataclass
class AnalyzeResult:
    """Result of an Evadr anti-bot analysis."""

    blocked: bool
    vendor: Optional[str] = None
    confidence: float = 0.0
    recommended_actions: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Webgrph — Site Mapping
# ---------------------------------------------------------------------------


@dataclass
class PageNode:
    """A single page discovered during a Webgrph crawl.

    Attributes:
        parent_url: The page above it in the tree (new in 0.6.0). In the
            default listing this is the page the crawl found it on.
        is_grouping: A grouping folder of the displayed tree, not a fetched
            page (``metadata.is_grouping``, new in 0.6.0). Only listed with
            ``include_grouping=True``.
        fetch_status: ``fetched``, ``unfetched`` (asked for and not
            obtained) or ``not_requested`` (``metadata.fetch_status``); None
            when the API sent none.
        fetch_error: Why an unfetched page was not obtained
            (``metadata.fetch_error``).

    The pages listing carries no HTTP status code and no
    ``crawl_parent_url``; the ``status_code`` and ``crawl_parent_url``
    attributes of earlier versions were always None and are gone.
    """

    url: str
    depth: int
    title: Optional[str] = None
    children: List[str] = field(default_factory=list)
    parent_url: Optional[str] = None
    is_grouping: bool = False
    fetch_status: Optional[str] = None
    fetch_error: Optional[str] = None


@dataclass
class CrawlResult:
    """Result of a Webgrph site crawl.

    ``total_pages`` is the pages the crawl found and ``max_depth_reached``
    the depth it reached; the tree's grouping folders are not counted.

    ``url`` is the URL the caller gave: the status answer carries none, so
    it is empty after ``wait_for_crawl`` unless passed there.

    Three outcomes other than a full crawl:

    * Held (``held`` True, ``status == "held_quota"``): the crawl is paused
      because the organization's quota ran out. ``success`` is False,
      ``error`` is None, ``message`` is the server's text and no pages are
      loaded. The crawl keeps its id and resumes by itself when quota
      returns (an upgrade, a top-up or a new billing period); after 30 days
      held it ends ``failed`` with ``error_code == "held_quota_expired"``.
      Call ``wait_for_crawl(crawl_id)`` again later.
    * Partial (``is_partial`` True): the crawl stopped before asking for
      every page it found; ``partial_reason`` is ``time_budget``,
      ``max_pages`` or ``error``. When ``resumable`` is True,
      ``continue_crawl(crawl_id)`` fetches the rest.
    * Failed, cancelled or still running at the waiter's timeout:
      ``success`` False and ``error`` set.

    ``pages_discovered``, ``pages_fetched``, ``pages_unfetched``,
    ``is_partial``, ``partial_reason``, ``resumable`` and ``error_code`` are
    None until the crawl has reported them.
    """

    success: bool
    crawl_id: str
    url: str
    total_pages: int
    max_depth_reached: int
    pages: List[PageNode] = field(default_factory=list)
    artifact_id: Optional[str] = None
    #: Set by the SDK: ``crawl`` loads every page, so always False.
    has_more: bool = False
    #: Set by the SDK: the number of page nodes loaded into ``pages``.
    total: int = 0
    next_cursor: Optional[str] = None
    error: Optional[str] = None
    #: queued, crawling, completed, failed, cancelled or held_quota.
    status: str = ""
    is_partial: Optional[bool] = None
    #: time_budget, max_pages or error.
    partial_reason: Optional[str] = None
    #: True when ``continue_crawl`` can fetch the pages this crawl left.
    resumable: Optional[bool] = None
    pages_discovered: Optional[int] = None
    pages_fetched: Optional[int] = None
    #: Pages asked for and not obtained.
    pages_unfetched: Optional[int] = None
    error_code: Optional[str] = None
    #: The server's text for a held crawl; None otherwise.
    message: Optional[str] = None
    #: True when the crawl is paused for quota (status ``held_quota``).
    held: bool = False

    @property
    def ok(self) -> bool:
        return self.success and self.error is None


@dataclass
class CrawlContinueResult:
    """The answer to ``webgrph.continue_crawl``: the crawl was queued again
    on the same id (``status`` "queued")."""

    success: bool
    crawl_id: str
    status: str = ""


@dataclass
class CrawlEvent:
    """A single server-sent event from a Webgrph crawl stream.

    The API sends pipeline events (kobe-scraper core/pipeline/models.py
    PipelineEvent): ``type`` is its ``event_type`` (``pipeline_step``,
    ``pipeline_error`` or ``pipeline_complete``). ``url``, ``pages_found``,
    ``total_pages`` and ``artifact_id`` are read from the event or its
    ``metadata`` when present.
    """

    type: str
    url: Optional[str] = None
    depth: Optional[int] = None
    pages_found: Optional[int] = None
    total_pages: Optional[int] = None
    artifact_id: Optional[str] = None
    stage_id: Optional[str] = None
    sub_status: Optional[str] = None
    progress_pct: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    status: Optional[str] = None
    message: Optional[str] = None
    error: Optional[Union[str, Dict[str, Any]]] = None
    sequence: Optional[int] = None

@dataclass
class CrawlExtractJob:
    """A crawl-extract job as ``webgrph.start_crawl_extract`` returns it
    (kobe-scraper modules/webgrph/crawl_extract_router.py)."""

    job_id: str
    crawl_id: str
    url: str
    status: str
    #: The page and depth limits the job runs with (the request's, capped
    #: by the plan).
    max_pages: Optional[int] = None
    max_depth: Optional[int] = None
    #: Paths of the job's routes: ``status``, ``results``, ``pages``,
    #: ``cancel``, ``export`` (by format), ``crawl_events``, ``events``.
    links: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CrawlExtractCrawl:
    """What a crawl-extract job's crawl really did (the status body's
    ``crawl`` object). The counts and ``is_partial`` are None until the
    crawl has reported them."""

    #: The crawl's own status; ``held_quota`` while it is paused for quota.
    status: Optional[str] = None
    is_partial: Optional[bool] = None
    #: time_budget, max_pages or error.
    partial_reason: Optional[str] = None
    pages_discovered: Optional[int] = None
    pages_fetched: Optional[int] = None
    pages_unfetched: Optional[int] = None
    cancelled: bool = False
    #: True when the crawl could not fetch its first page.
    root_unfetched: bool = False
    #: The crawl's error, set only when the crawl failed.
    error: Optional[str] = None
    error_code: Optional[str] = None


@dataclass
class CrawlExtractStatus:
    """The state of a crawl-extract job (``webgrph.get_crawl_extract``).

    ``status`` is ``queued``, ``crawling``, ``extracting``, ``completed``,
    ``failed`` or ``cancelled``.

    The job itself is never held for quota: it keeps waiting while its
    crawl is. ``held`` is True then (``crawl.status == "held_quota"``); the
    crawl resumes by itself when the organization's quota returns, and
    after 30 days held it ends failed with ``held_quota_expired``.

    A completed job whose ``crawl.is_partial`` is True holds the rows of the
    pages that crawl fetched, not of the whole site."""

    job_id: str
    status: str
    crawl_id: str = ""
    url: str = ""
    cancel_requested: bool = False
    pages_crawled: int = 0
    #: None until the crawl has finished.
    pages_total: Optional[int] = None
    pages_extracted: int = 0
    pages_failed: int = 0
    items: int = 0
    error: Optional[str] = None
    error_code: Optional[str] = None
    #: The request the job was started with.
    request: Dict[str, Any] = field(default_factory=dict)
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    updated_at: Optional[str] = None
    links: Dict[str, Any] = field(default_factory=dict)
    #: Pages by how they were extracted.
    pages_by_method: Dict[str, int] = field(default_factory=dict)
    #: The row shapes found: ``{shape, kind, rows, page_types, fields}``.
    shapes: List[Dict[str, Any]] = field(default_factory=list)
    #: What the job's crawl did; None when the API sent no crawl object.
    crawl: Optional[CrawlExtractCrawl] = None

    @property
    def finished(self) -> bool:
        return self.status in ("completed", "failed", "cancelled")

    @property
    def held(self) -> bool:
        """True while the job's crawl is paused for quota."""
        return self.crawl is not None and self.crawl.status == "held_quota"

    @property
    def ok(self) -> bool:
        return self.status == "completed"


@dataclass
class CrawlExtractRow:
    """One extracted row: an item of a listing page (``row_kind`` "item")
    or a whole page's fields ("page")."""

    page_url: str
    row_kind: str
    item_index: int = 0
    data: Dict[str, Any] = field(default_factory=dict)
    page_type: Optional[str] = None
    shape: Optional[str] = None


@dataclass
class CrawlExtractResultsPage:
    """One page of a job's rows. ``next_cursor`` is None on the last page."""

    job_id: str
    status: str
    total: int = 0
    count: int = 0
    rows: List[CrawlExtractRow] = field(default_factory=list)
    next_cursor: Optional[str] = None


@dataclass
class CrawlExtractPage:
    """One crawled page of a job and what its extraction came to."""

    page_seq: int
    page_url: str
    status: str
    page_type: Optional[str] = None
    title: Optional[str] = None
    method: Optional[str] = None
    item_count: int = 0
    detail: Any = None
    extracted_at: Optional[str] = None


@dataclass
class CrawlExtractPagesResult:
    """Some of a job's pages (``webgrph.get_crawl_extract_pages``)."""

    job_id: str
    status: str
    count: int = 0
    offset: int = 0
    pages: List[CrawlExtractPage] = field(default_factory=list)


@dataclass
class CrawlExtractCancelResult:
    """Result of ``webgrph.cancel_crawl_extract``. ``status`` is
    ``cancelled`` (the job had not started) or ``cancelling``."""

    success: bool
    job_id: str
    crawl_id: str = ""
    status: str = ""


@dataclass
class ExportCrawl:
    """What the crawl behind a crawl-extract export did, read from the
    export's ``X-Crawl-*`` response headers. Each value is None when its
    header was not sent (the crawl had not reported it)."""

    #: ``X-Crawl-Status``.
    status: Optional[str] = None
    #: ``X-Crawl-Partial``.
    is_partial: Optional[bool] = None
    #: ``X-Crawl-Partial-Reason``: time_budget, max_pages or error.
    partial_reason: Optional[str] = None
    #: ``X-Crawl-Pages-Discovered``.
    pages_discovered: Optional[int] = None
    #: ``X-Crawl-Pages-Fetched``.
    pages_fetched: Optional[int] = None
    #: ``X-Crawl-Pages-Unfetched``.
    pages_unfetched: Optional[int] = None
    #: ``X-Crawl-Cancelled``.
    cancelled: Optional[bool] = None
    #: ``X-Crawl-Root-Unfetched``: the crawl could not fetch its first page.
    root_unfetched: Optional[bool] = None


@dataclass
class SavedExport:
    """An export written to a file (``webgrph.download_crawl_extract``,
    ``client.download_batch_job``)."""

    path: str
    bytes: int
    content_type: Optional[str] = None
    filename: Optional[str] = None
    #: ``X-Job-Status``: set for crawl-extract exports; None for batch
    #: exports, whose route sends no such header.
    job_status: Optional[str] = None
    #: From the ``X-Crawl-*`` headers: set for crawl-extract exports; None
    #: when the response carries no ``X-Crawl-*`` header (a job with no
    #: crawl row, and every batch export).
    crawl: Optional[ExportCrawl] = None


# ---------------------------------------------------------------------------
# Crawl Orchestrator — High-level site crawl
# ---------------------------------------------------------------------------


@dataclass
class CrawlPage:
    """A single page result from a crawl() orchestrator call."""

    success: bool
    url: str
    status_code: int = 0
    tier_used: int = 0
    html: Optional[str] = None
    structured_data: Optional[Dict[str, Any]] = None
    artifact_id: Optional[str] = None
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        """True when the page was fetched successfully."""
        return self.success and self.error is None


@dataclass
class SiteCrawlResult:
    """Result of a crawl() orchestrator call — discover, fetch, and optionally extract.

    When the crawl is held for quota, ``held`` is True, ``success`` False,
    ``error`` None, ``message`` the server's text and ``pages`` empty; the
    crawl resumes by itself on ``crawl_id`` (see ``CrawlResult``)."""

    success: bool
    url: str
    total_pages_discovered: int = 0
    pages_fetched: int = 0
    pages_failed: int = 0
    pages: List[CrawlPage] = field(default_factory=list)
    crawl_artifact_id: Optional[str] = None
    error: Optional[str] = None
    #: The Webgrph crawl's id (for ``webgrph.wait_for_crawl``).
    crawl_id: str = ""
    #: The Webgrph crawl's status.
    crawl_status: str = ""
    #: True when the crawl is paused for quota (status ``held_quota``).
    held: bool = False
    #: The server's text for a held crawl; None otherwise.
    message: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.success and self.error is None


@dataclass
class CrawlProgressEvent:
    """A single progress event from crawl_stream()."""

    type: str
    url: Optional[str] = None
    page: Optional[int] = None
    total: Optional[int] = None
    success: Optional[bool] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Nexus — Strategy Engine
# ---------------------------------------------------------------------------


@dataclass
class NexusAnalyzeResult:
    """Result of nexus.analyze().

    The API's answer has no ``error`` field: a failed call raises."""

    url: str
    perception_id: str = ""
    reasoning_id: Optional[str] = None
    strategy: Dict[str, Any] = field(default_factory=dict)
    page_type: str = "unknown"
    confidence: float = 0.0
    artifact_id: Optional[str] = None

    @property
    def ok(self) -> bool:
        """Always True: a result exists only when the call succeeded (a
        failed call raises). Kept so code written for 0.6.0 still runs."""
        return True

@dataclass
class NexusSynthesisResult:
    """Result of nexus.synthesize().

    The API's answer has no ``error`` field: a failed call raises."""

    url: str
    goal: str
    strategy_id: str = ""
    strategy_name: str = ""
    strategy_type: Optional[str] = None
    #: The generated extraction program.
    program: str = ""
    steps: List[Dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.0
    synthesis_time_ms: int = 0

    @property
    def ok(self) -> bool:
        """Always True: a result exists only when the call succeeded (a
        failed call raises). Kept so code written for 0.6.0 still runs."""
        return True

@dataclass
class NexusSafetyCheck:
    """One safety property checked by nexus.verify()."""

    property: str
    passed: bool
    details: str = ""

@dataclass
class NexusVerifyResult:
    """Result of nexus.verify() (kobe-scraper modules/nexus/router.py
    VerifyResponse). The API's answer has no ``error`` field: a failed call
    raises."""

    strategy_id: str
    verified: bool
    safety_score: float = 0.0
    violations: List[str] = field(default_factory=list)
    #: "verified" or "unsafe" (None if the API sent none).
    status: Optional[str] = None
    risk_score: float = 0.0
    safety_checks: List[NexusSafetyCheck] = field(default_factory=list)
    verification_result_id: Optional[str] = None
    duration_ms: int = 0

    @property
    def ok(self) -> bool:
        """True when the strategy was verified (the same as ``verified``)."""
        return self.verified

# ---------------------------------------------------------------------------
# Parlyr — Conversational NLP
# ---------------------------------------------------------------------------


@dataclass
class ParseResult:
    """Result of a Parlyr stateless parse call."""

    intent: str
    confidence: float
    tier: int
    source: str
    entities: Dict[str, Any] = field(default_factory=dict)
    requires_action: bool = False
    clarification_needed: Optional[str] = None
    reasoning: Optional[str] = None
    detected_url: Optional[str] = None

    @property
    def ok(self) -> bool:
        return not self.requires_action


@dataclass
class ChatEvent:
    """A single server-sent event from a Parlyr chat stream.

    ``type`` is one of thinking, interpretation, progress, results, error,
    warning, auth_required, mfa_required, clarification, export_ready or
    text (kobe-scraper application/services/chat_orchestrator.py
    ChatEventType). The stream's closing ``end`` event is not yielded.
    """

    type: str
    content: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
    #: Suggested next steps, ``[{"id", "label", "primary"?}]``.
    actions: Optional[List[Dict[str, Any]]] = None
    timestamp: Optional[str] = None

    @property
    def event(self) -> str:
        """The SSE event name (the same as ``type``)."""
        return self.type


@dataclass
class ChatTurn:
    """The fully-assembled result of one Parlyr chat turn.

    Attributes:
        response: The ``content`` of the turn's ``text`` and
            ``clarification`` events, joined by newlines.
        intent: ``interpretation.get("intent")``. The API's interpretation
            events carry no intent key today (kobe-scraper
            application/services/chat_orchestrator.py), so this is usually
            None; the plan itself is ``interpretation``.
        interpretation: The ``data`` of the last ``interpretation`` event
            (``url``, ``entity``, ``fields``, ``summary``, …), or None.
        results: The ``data`` of each ``results`` event.
        errors: The turn's ``error`` events (not raised; ``ok`` is False).
        warnings: The turn's ``warning`` events.
        events: Every event of the turn, in order.
    """

    session_id: str
    response: str = ""
    intent: Optional[str] = None
    interpretation: Optional[Dict[str, Any]] = None
    results: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[ChatEvent] = field(default_factory=list)
    warnings: List[ChatEvent] = field(default_factory=list)
    events: List[ChatEvent] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


# ---------------------------------------------------------------------------
# Fetchyr — RPA & Authentication
# ---------------------------------------------------------------------------


@dataclass
class SessionResult:
    """Result of fetchyr.authenticate()."""

    success: bool
    session_id: str
    #: The URL logged into (the request's target).
    url: str
    artifact_id: Optional[str] = None
    target_domain: Optional[str] = None
    auth_method: Optional[str] = None
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.success and self.error is None

@dataclass
class LoginSession:
    """The answer to ``fetchyr.start_login_session``.

    ``status`` is ``waiting_for_login`` (method "interactive": answer the
    auth chain named by ``discovery_id`` and ``next``) or ``ready`` (method
    "cookies": ``session_artifact_id`` can be used at once)."""

    method: str
    status: str
    target_url: str
    discovery_id: Optional[str] = None
    session_artifact_id: Optional[str] = None
    #: The calls to make next, by name.
    next: Dict[str, str] = field(default_factory=dict)
    #: method "cookies": how many of the cookies were kept.
    cookies_kept: Optional[int] = None
    #: method "cookies": the names of the cookies that were dropped.
    cookies_dropped: List[str] = field(default_factory=list)
    protections: Dict[str, Any] = field(default_factory=dict)
    message: str = ""


@dataclass
class SessionStatus:
    """A login session's state (``fetchyr.get_session``,
    ``fetchyr.resume_session``).

    ``status`` is ``active``, ``paused``, ``EXPIRED`` or ``INVALIDATED``.
    A paused session has ``pause_reason`` ``logged_out``, ``rate_limited``
    or ``challenged``."""

    artifact_id: str
    status: str
    target_domain: Optional[str] = None
    auth_method: Optional[str] = None
    created_at: Optional[str] = None
    expires_at: Optional[str] = None
    last_used_at: Optional[str] = None
    paused_at: Optional[str] = None
    pause_reason: Optional[str] = None
    pause_message: Optional[str] = None
    #: What the session presents (no cookie values).
    identity: Dict[str, Any] = field(default_factory=dict)
    requests_this_hour: Optional[int] = None
    protections: Dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkflowResult:
    """An RPA workflow."""

    workflow_id: str
    name: str
    description: Optional[str] = None
    workflow_type: Optional[str] = None
    steps: List[Dict[str, Any]] = field(default_factory=list)
    is_active: bool = True
    created_at: str = ""
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None

@dataclass
class WorkflowExecutionResult:
    """A workflow execution."""

    execution_id: str
    workflow_id: str
    status: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.status == "completed" and self.error is None

@dataclass
class FormDetectionResult:
    """Result of fetchyr.detect_forms()."""

    url: str = ""
    #: The detected form fields.
    forms: List[Dict[str, Any]] = field(default_factory=list)
    total_forms: int = 0
    login_form_detected: bool = False
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None

@dataclass
class MfaDetectionResult:
    """Result of fetchyr.detect_mfa()."""

    mfa_detected: bool = False
    challenge_id: Optional[str] = None
    mfa_type: Optional[str] = None
    message: Optional[str] = None
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None

@dataclass
class MfaChallenge:
    """A queued MFA challenge."""

    id: str
    status: str = ""
    session_id: Optional[str] = None
    mfa_type: Optional[str] = None
    challenge_data: Dict[str, Any] = field(default_factory=dict)
    expires_at: Optional[str] = None
    created_at: Optional[str] = None

@dataclass
class DuplicateCheckResult:
    """Result of fetchyr.check_duplicate()."""

    is_duplicate: bool
    original_url: Optional[str] = None
    similarity_score: Optional[float] = None
    match_type: Optional[str] = None

# ---------------------------------------------------------------------------
# Kolektr — Data Extraction
# ---------------------------------------------------------------------------


class SchemaField(TypedDict, total=False):
    """One extraction field (kobe-scraper modules/kolektr/router.py FieldSpec).

    ``name`` is required. ``selector`` is CSS; ``attribute`` reads that
    attribute instead of the text; ``type`` ``"list"`` returns every match
    (default ``"text"``: the first match).
    """

    name: str
    selector: Optional[str]
    attribute: Optional[str]
    type: str


class SchemaSpec(TypedDict, total=False):
    """A full extraction spec (kobe-scraper modules/kolektr/router.py SchemaSpec).

    ``item_selector`` (new in 0.6.0): CSS for the repeated item on a list
    page; one record per match, each field read inside it.
    """

    fields: List[SchemaField]
    item_selector: Optional[str]
    pagination: bool
    max_pages: int
    output_format: str


@dataclass
class ExtractionResult:
    """Result of a Kolektr extraction operation."""

    success: bool
    url: str
    method: str
    records: List[Dict[str, Any]] = field(default_factory=list)
    total_records: int = 0
    pages_scraped: int = 0
    artifact_id: Optional[str] = None
    job_id: Optional[str] = None
    error: Optional[str] = None
    #: For a fresh scrape, the level it ran at: ``level1`` or ``level2``.
    level: Optional[str] = None
    #: Why that level: ``requested``, or (prefixed ``auto:``) what automatic
    #: mode chose it for.
    level_reason: Optional[str] = None
    #: True when a login page was detected at the target URL.
    auth_required: bool = False
    #: The auth-chain discovery id when ``auth_required`` is true.
    discovery_id: Optional[str] = None
    #: When ``auth_required``: how to log in with your own account
    #: (``fetchyr.start_login_session``) and pass the session artifact id.
    login_options: Optional[Dict[str, Any]] = None

    @property
    def ok(self) -> bool:
        return self.success and self.error is None
