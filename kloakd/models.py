"""
KLOAKD SDK — Result models.

All models are plain dataclasses with no framework coupling.
They are the return types of every namespace method and can be
serialised to dict via dataclasses.asdict() or inspected directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

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
    """A single page discovered during a Webgrph crawl."""

    url: str
    depth: int
    title: Optional[str] = None
    status_code: Optional[int] = None
    children: List[str] = field(default_factory=list)


@dataclass
class CrawlResult:
    """Result of a Webgrph site crawl."""

    success: bool
    crawl_id: str
    url: str
    total_pages: int
    max_depth_reached: int
    pages: List[PageNode] = field(default_factory=list)
    artifact_id: Optional[str] = None
    has_more: bool = False
    total: int = 0
    next_cursor: Optional[str] = None
    error: Optional[str] = None
    #: queued, crawling, completed, failed or cancelled.
    status: str = ""

    @property
    def ok(self) -> bool:
        return self.success and self.error is None


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
    """Result of a crawl() orchestrator call — discover, fetch, and optionally extract."""

    success: bool
    url: str
    total_pages_discovered: int = 0
    pages_fetched: int = 0
    pages_failed: int = 0
    pages: List[CrawlPage] = field(default_factory=list)
    crawl_artifact_id: Optional[str] = None
    error: Optional[str] = None

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
# Nexus — Strategy Engine (5-layer cognitive pipeline)
# ---------------------------------------------------------------------------


@dataclass
class NexusAnalyzeResult:
    """Result of nexus.analyze()."""

    url: str
    perception_id: str = ""
    reasoning_id: Optional[str] = None
    strategy: Dict[str, Any] = field(default_factory=dict)
    page_type: str = "unknown"
    confidence: float = 0.0
    artifact_id: Optional[str] = None
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None

@dataclass
class NexusSynthesisResult:
    """Result of nexus.synthesize()."""

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
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None

@dataclass
class NexusVerifyResult:
    """Result of nexus.verify()."""

    strategy_id: str
    verified: bool
    safety_score: float = 0.0
    violations: List[str] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.verified and self.error is None

@dataclass
class NexusExecuteResult:
    """Result of nexus.execute()."""

    url: str
    strategy_id: str
    success: bool
    records: List[Dict[str, Any]] = field(default_factory=list)
    artifact_id: Optional[str] = None
    duration_ms: int = 0
    error: Optional[str] = None
    # The id nexus.knowledge() takes for this execution (None if the API sent none).
    execution_result_id: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.success and self.error is None

@dataclass
class NexusKnowledgeResult:
    """Result of nexus.knowledge()."""

    execution_result_id: str
    learned_concepts: List[Dict[str, Any]] = field(default_factory=list)
    patterns: List[Dict[str, Any]] = field(default_factory=list)
    total_patterns: int = 0
    duration_ms: int = 0
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None

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
    has_more: bool = False
    total: int = 0
    error: Optional[str] = None
    #: True when a login page was detected at the target URL.
    auth_required: bool = False
    #: The auth-chain discovery id when ``auth_required`` is true.
    discovery_id: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.success and self.error is None
