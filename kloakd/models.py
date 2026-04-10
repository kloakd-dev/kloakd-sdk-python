"""
KLOAKD SDK — Result models.

All models are plain dataclasses with no framework coupling.
They are the return types of every namespace method and can be
serialised to dict via dataclasses.asdict() or inspected directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Evadr — Anti-Bot Intelligence
# ---------------------------------------------------------------------------


@dataclass
class FetchResult:
    """Result of an Evadr fetch operation."""

    success: bool
    url: str
    status_code: int
    tier_used: int
    html: Optional[str] = None
    vendor_detected: Optional[str] = None
    anti_bot_bypassed: bool = False
    artifact_id: Optional[str] = None
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        """True when the fetch succeeded with no error."""
        return self.success and self.error is None


@dataclass
class FetchEvent:
    """A single server-sent event from an Evadr async fetch stream."""

    type: str
    tier: Optional[int] = None
    vendor: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


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
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.success and self.error is None


@dataclass
class CrawlEvent:
    """A single server-sent event from a Webgrph crawl stream."""

    type: str
    url: Optional[str] = None
    depth: Optional[int] = None
    pages_found: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Skanyr — API Discovery
# ---------------------------------------------------------------------------


@dataclass
class ApiEndpoint:
    """A single API endpoint discovered by Skanyr."""

    url: str
    method: str
    api_type: str
    confidence: float = 0.0
    parameters: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DiscoverResult:
    """Result of a Skanyr two-phase API discovery."""

    success: bool
    discovery_id: str
    url: str
    total_endpoints: int
    endpoints: List[ApiEndpoint] = field(default_factory=list)
    artifact_id: Optional[str] = None
    has_more: bool = False
    total: int = 0
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.success and self.error is None


@dataclass
class DiscoverEvent:
    """A single server-sent event from a Skanyr discovery stream."""

    type: str
    endpoint_url: Optional[str] = None
    api_type: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Nexus — Strategy Engine (5-layer cognitive pipeline)
# ---------------------------------------------------------------------------


@dataclass
class NexusAnalyzeResult:
    """Result of a Nexus perception (analyze) call."""

    perception_id: str
    strategy: Dict[str, Any] = field(default_factory=dict)
    page_type: str = "unknown"
    complexity_level: str = "unknown"
    artifact_id: Optional[str] = None
    duration_ms: int = 0
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass
class NexusSynthesisResult:
    """Result of a Nexus synthesize call."""

    strategy_id: str
    strategy_name: str = ""
    generated_code: str = ""
    artifact_id: Optional[str] = None
    synthesis_time_ms: int = 0
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass
class NexusVerifyResult:
    """Result of a Nexus verification call."""

    verification_result_id: str
    is_safe: bool
    risk_score: float = 0.0
    safety_score: float = 1.0
    violations: List[str] = field(default_factory=list)
    duration_ms: int = 0
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.is_safe and self.error is None


@dataclass
class NexusExecuteResult:
    """Result of a Nexus execute call."""

    execution_result_id: str
    success: bool
    records: List[Dict[str, Any]] = field(default_factory=list)
    artifact_id: Optional[str] = None
    duration_ms: int = 0
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.success and self.error is None


@dataclass
class NexusKnowledgeResult:
    """Result of a Nexus knowledge (learn) call."""

    learned_concepts: List[Dict[str, Any]] = field(default_factory=list)
    learned_patterns: List[Dict[str, Any]] = field(default_factory=list)
    has_more: bool = False
    total: int = 0
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
    """A single server-sent event from a Parlyr chat stream."""

    event: str
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ChatTurn:
    """The fully-assembled result of one Parlyr chat turn."""

    session_id: str
    intent: str
    confidence: float
    tier: int
    response: str
    entities: Dict[str, Any] = field(default_factory=dict)
    requires_action: bool = False
    clarification_needed: Optional[str] = None


# ---------------------------------------------------------------------------
# Fetchyr — RPA & Authentication
# ---------------------------------------------------------------------------


@dataclass
class SessionResult:
    """Result of a Fetchyr RPA login operation."""

    success: bool
    session_id: str
    url: str
    artifact_id: Optional[str] = None
    screenshot_url: Optional[str] = None
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.success and self.error is None


@dataclass
class FetchyrResult:
    """Result of a Fetchyr authenticated fetch operation."""

    success: bool
    url: str
    status_code: int
    html: Optional[str] = None
    artifact_id: Optional[str] = None
    session_artifact_id: Optional[str] = None
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.success and self.error is None


@dataclass
class WorkflowResult:
    """Result of a Fetchyr create_workflow call."""

    workflow_id: str
    name: str
    steps: List[Dict[str, Any]] = field(default_factory=list)
    url: Optional[str] = None
    created_at: str = ""
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass
class WorkflowExecutionResult:
    """Result of a Fetchyr execute_workflow or get_execution call."""

    execution_id: str
    workflow_id: str
    status: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    records: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.status == "completed" and self.error is None


@dataclass
class FormDetectionResult:
    """Result of a Fetchyr detect_forms call."""

    forms: List[Dict[str, Any]] = field(default_factory=list)
    total_forms: int = 0
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass
class MfaDetectionResult:
    """Result of a Fetchyr detect_mfa call."""

    mfa_detected: bool = False
    challenge_id: Optional[str] = None
    mfa_type: Optional[str] = None
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass
class MfaResult:
    """Result of a Fetchyr submit_mfa call."""

    success: bool
    session_artifact_id: Optional[str] = None
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.success and self.error is None


@dataclass
class DeduplicationResult:
    """Result of a Fetchyr check_duplicates call."""

    unique_records: List[Dict[str, Any]] = field(default_factory=list)
    duplicate_count: int = 0
    total_input: int = 0
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None


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

    @property
    def ok(self) -> bool:
        return self.success and self.error is None
