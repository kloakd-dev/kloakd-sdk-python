"""
KLOAKD SDK — Fetchyr module namespace.

Fetchyr is KLOAKD's RPA & Authentication layer. It performs real browser
logins, produces reusable AUTHENTICATED_SESSION artifacts, and manages
workflows, form detection, MFA handling, and deduplication.

Usage::

    # Login and produce a reusable session artifact
    session = client.fetchyr.login(
        url="https://app.example.com/login",
        username_selector="#email",
        password_selector="#password",
        username="user@example.com",
        password="s3cr3t",
    )

    # Reuse the session across modules
    html = client.fetchyr.fetch("https://app.example.com/dashboard", session.artifact_id)
    crawl = client.webgrph.crawl("https://app.example.com", session_artifact_id=session.artifact_id)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional

from kloakd.models import (
    DeduplicationResult,
    FetchyrResult,
    FormDetectionResult,
    MfaDetectionResult,
    MfaResult,
    SessionResult,
    WorkflowExecutionResult,
    WorkflowResult,
)

if TYPE_CHECKING:
    from kloakd._http import _AsyncHttpTransport, _HttpTransport


class FetchyrNamespace:
    """Synchronous Fetchyr operations. Access via ``client.fetchyr``."""

    def __init__(self, transport: "_HttpTransport") -> None:
        self._t = transport

    # ── Session management ────────────────────────────────────────────

    def login(
        self,
        url: str,
        username_selector: str,
        password_selector: str,
        username: str,
        password: str,
        submit_selector: Optional[str] = None,
        success_url_contains: Optional[str] = None,
    ) -> SessionResult:
        """
        Perform an RPA browser login and produce an AUTHENTICATED_SESSION artifact.

        The artifact_id can be reused across Evadr, Webgrph, Skanyr, and
        Fetchyr.fetch() without triggering another login.

        Args:
            url: Login page URL.
            username_selector: CSS selector for the username/email field.
            password_selector: CSS selector for the password field.
            username: Login credential.
            password: Login password.
            submit_selector: CSS selector for the submit button.
            success_url_contains: URL substring confirming successful login.

        Returns:
            SessionResult with artifact_id for downstream reuse.
        """
        body: Dict[str, Any] = {
            "url": url,
            "username_selector": username_selector,
            "password_selector": password_selector,
            "username": username,
            "password": password,
        }
        if submit_selector:
            body["submit_selector"] = submit_selector
        if success_url_contains:
            body["success_url_contains"] = success_url_contains

        raw = self._t.post("fetchyr/login", body)
        return SessionResult(
            success=raw.get("success", False),
            session_id=raw.get("session_id", ""),
            url=raw.get("url", url),
            artifact_id=raw.get("artifact_id"),
            screenshot_url=raw.get("screenshot_url"),
            error=raw.get("error"),
        )

    def fetch(
        self,
        url: str,
        session_artifact_id: str,
        wait_for_selector: Optional[str] = None,
        extract_html: bool = True,
    ) -> FetchyrResult:
        """
        Perform an authenticated fetch by reusing an AUTHENTICATED_SESSION artifact.

        Args:
            url: Target URL.
            session_artifact_id: Artifact ID from login().
            wait_for_selector: CSS selector to wait for before capturing HTML.
            extract_html: Whether to return full HTML. Default True.

        Returns:
            FetchyrResult with html and artifact_id.
        """
        body: Dict[str, Any] = {
            "url": url,
            "session_artifact_id": session_artifact_id,
            "extract_html": extract_html,
        }
        if wait_for_selector:
            body["wait_for_selector"] = wait_for_selector

        raw = self._t.post("fetchyr/fetch", body)
        return FetchyrResult(
            success=raw.get("success", False),
            url=raw.get("url", url),
            status_code=raw.get("status_code", 0),
            html=raw.get("html"),
            artifact_id=raw.get("artifact_id"),
            session_artifact_id=session_artifact_id,
            error=raw.get("error"),
        )

    def get_session(self, artifact_id: str) -> Dict[str, Any]:
        """Retrieve session artifact metadata by ID."""
        return self._t.get(f"fetchyr/sessions/{artifact_id}")

    def invalidate_session(self, artifact_id: str) -> None:
        """Explicitly invalidate a session artifact (e.g. after logout)."""
        self._t.post(f"fetchyr/sessions/{artifact_id}/invalidate", {})

    # ── Workflow automation ───────────────────────────────────────────

    def create_workflow(
        self,
        name: str,
        steps: List[Dict[str, Any]],
        url: Optional[str] = None,
    ) -> WorkflowResult:
        """
        Create a reusable RPA workflow definition.

        Args:
            name: Human-readable workflow name.
            steps: List of step dicts defining actions (click, fill, wait, etc.)
            url: Optional starting URL for the workflow.

        Returns:
            WorkflowResult with workflow_id.
        """
        body: Dict[str, Any] = {"name": name, "steps": steps}
        if url:
            body["url"] = url

        raw = self._t.post("fetchyr/workflows", body)
        return WorkflowResult(
            workflow_id=raw.get("workflow_id", ""),
            name=raw.get("name", name),
            steps=raw.get("steps", steps),
            url=raw.get("url"),
            created_at=raw.get("created_at", ""),
            error=raw.get("error"),
        )

    def execute_workflow(self, workflow_id: str) -> WorkflowExecutionResult:
        """
        Execute a workflow and return the execution result.

        Args:
            workflow_id: ID from create_workflow().

        Returns:
            WorkflowExecutionResult with status and records.
        """
        raw = self._t.post(f"fetchyr/workflows/{workflow_id}/execute", {})
        return WorkflowExecutionResult(
            execution_id=raw.get("execution_id", ""),
            workflow_id=workflow_id,
            status=raw.get("status", "pending"),
            started_at=raw.get("started_at"),
            completed_at=raw.get("completed_at"),
            records=raw.get("records", []),
            error=raw.get("error"),
        )

    def get_execution(
        self, workflow_id: str, execution_id: str
    ) -> WorkflowExecutionResult:
        """
        Poll a workflow execution by ID.

        Args:
            workflow_id: Workflow identifier.
            execution_id: Execution identifier from execute_workflow().

        Returns:
            WorkflowExecutionResult with current status.
        """
        raw = self._t.get(f"fetchyr/workflows/{workflow_id}/executions/{execution_id}")
        return WorkflowExecutionResult(
            execution_id=execution_id,
            workflow_id=workflow_id,
            status=raw.get("status", "pending"),
            started_at=raw.get("started_at"),
            completed_at=raw.get("completed_at"),
            records=raw.get("records", []),
            error=raw.get("error"),
        )

    # ── Form detection ────────────────────────────────────────────────

    def detect_forms(
        self,
        url: str,
        session_artifact_id: Optional[str] = None,
    ) -> FormDetectionResult:
        """
        Detect and analyse all forms on a page.

        Args:
            url: Target URL.
            session_artifact_id: Optional AUTHENTICATED_SESSION artifact.

        Returns:
            FormDetectionResult with forms list (selector, fields, confidence).
        """
        body: Dict[str, Any] = {"url": url}
        if session_artifact_id:
            body["session_artifact_id"] = session_artifact_id

        raw = self._t.post("fetchyr/detect-forms", body)
        return FormDetectionResult(
            forms=raw.get("forms", []),
            total_forms=raw.get("total_forms", 0),
            error=raw.get("error"),
        )

    # ── MFA handling ──────────────────────────────────────────────────

    def detect_mfa(
        self,
        url: str,
        session_artifact_id: Optional[str] = None,
    ) -> MfaDetectionResult:
        """
        Detect whether a page requires MFA and identify the challenge type.

        Args:
            url: Target URL (post-login redirect).
            session_artifact_id: Optional AUTHENTICATED_SESSION artifact.

        Returns:
            MfaDetectionResult with mfa_detected, challenge_id, mfa_type.
        """
        body: Dict[str, Any] = {"url": url}
        if session_artifact_id:
            body["session_artifact_id"] = session_artifact_id

        raw = self._t.post("fetchyr/detect-mfa", body)
        return MfaDetectionResult(
            mfa_detected=raw.get("mfa_detected", False),
            challenge_id=raw.get("challenge_id"),
            mfa_type=raw.get("mfa_type"),
            error=raw.get("error"),
        )

    def submit_mfa(self, challenge_id: str, code: str) -> MfaResult:
        """
        Submit an MFA code to complete authentication.

        Args:
            challenge_id: challenge_id from detect_mfa().
            code: TOTP, SMS, or backup code.

        Returns:
            MfaResult with success and updated session_artifact_id.
        """
        raw = self._t.post("fetchyr/submit-mfa", {
            "challenge_id": challenge_id,
            "code": code,
        })
        return MfaResult(
            success=raw.get("success", False),
            session_artifact_id=raw.get("session_artifact_id"),
            error=raw.get("error"),
        )

    # ── Deduplication ─────────────────────────────────────────────────

    def check_duplicates(
        self,
        records: List[Dict[str, Any]],
        domain: Optional[str] = None,
    ) -> DeduplicationResult:
        """
        Identify and remove duplicate records from an extraction result.

        Args:
            records: List of extracted record dicts.
            domain: Optional domain context for domain-aware dedup.

        Returns:
            DeduplicationResult with unique_records and duplicate_count.
        """
        body: Dict[str, Any] = {"records": records}
        if domain:
            body["domain"] = domain

        raw = self._t.post("fetchyr/deduplicate", body)
        return DeduplicationResult(
            unique_records=raw.get("unique_records", []),
            duplicate_count=raw.get("duplicate_count", 0),
            total_input=raw.get("total_input", len(records)),
            error=raw.get("error"),
        )


class AsyncFetchyrNamespace:
    """Async Fetchyr operations. Access via ``async_client.fetchyr``."""

    def __init__(self, transport: "_AsyncHttpTransport") -> None:
        self._t = transport

    async def login(
        self,
        url: str,
        username_selector: str,
        password_selector: str,
        username: str,
        password: str,
        submit_selector: Optional[str] = None,
        success_url_contains: Optional[str] = None,
    ) -> SessionResult:
        """Async equivalent of FetchyrNamespace.login."""
        body: Dict[str, Any] = {
            "url": url,
            "username_selector": username_selector,
            "password_selector": password_selector,
            "username": username,
            "password": password,
        }
        if submit_selector:
            body["submit_selector"] = submit_selector
        if success_url_contains:
            body["success_url_contains"] = success_url_contains
        raw = await self._t.post("fetchyr/login", body)
        return SessionResult(
            success=raw.get("success", False),
            session_id=raw.get("session_id", ""),
            url=raw.get("url", url),
            artifact_id=raw.get("artifact_id"),
            screenshot_url=raw.get("screenshot_url"),
            error=raw.get("error"),
        )

    async def fetch(
        self,
        url: str,
        session_artifact_id: str,
        wait_for_selector: Optional[str] = None,
        extract_html: bool = True,
    ) -> FetchyrResult:
        """Async equivalent of FetchyrNamespace.fetch."""
        body: Dict[str, Any] = {
            "url": url,
            "session_artifact_id": session_artifact_id,
            "extract_html": extract_html,
        }
        if wait_for_selector:
            body["wait_for_selector"] = wait_for_selector
        raw = await self._t.post("fetchyr/fetch", body)
        return FetchyrResult(
            success=raw.get("success", False),
            url=raw.get("url", url),
            status_code=raw.get("status_code", 0),
            html=raw.get("html"),
            artifact_id=raw.get("artifact_id"),
            session_artifact_id=session_artifact_id,
            error=raw.get("error"),
        )

    async def get_session(self, artifact_id: str) -> Dict[str, Any]:
        """Async equivalent of FetchyrNamespace.get_session."""
        return await self._t.get(f"fetchyr/sessions/{artifact_id}")

    async def invalidate_session(self, artifact_id: str) -> None:
        """Async equivalent of FetchyrNamespace.invalidate_session."""
        await self._t.post(f"fetchyr/sessions/{artifact_id}/invalidate", {})

    async def create_workflow(
        self, name: str, steps: List[Dict[str, Any]], url: Optional[str] = None
    ) -> WorkflowResult:
        """Async equivalent of FetchyrNamespace.create_workflow."""
        body: Dict[str, Any] = {"name": name, "steps": steps}
        if url:
            body["url"] = url
        raw = await self._t.post("fetchyr/workflows", body)
        return WorkflowResult(
            workflow_id=raw.get("workflow_id", ""),
            name=raw.get("name", name),
            steps=raw.get("steps", steps),
            url=raw.get("url"),
            created_at=raw.get("created_at", ""),
            error=raw.get("error"),
        )

    async def execute_workflow(self, workflow_id: str) -> WorkflowExecutionResult:
        """Async equivalent of FetchyrNamespace.execute_workflow."""
        raw = await self._t.post(f"fetchyr/workflows/{workflow_id}/execute", {})
        return WorkflowExecutionResult(
            execution_id=raw.get("execution_id", ""),
            workflow_id=workflow_id,
            status=raw.get("status", "pending"),
            started_at=raw.get("started_at"),
            completed_at=raw.get("completed_at"),
            records=raw.get("records", []),
            error=raw.get("error"),
        )

    async def get_execution(
        self, workflow_id: str, execution_id: str
    ) -> WorkflowExecutionResult:
        """Async equivalent of FetchyrNamespace.get_execution."""
        raw = await self._t.get(
            f"fetchyr/workflows/{workflow_id}/executions/{execution_id}"
        )
        return WorkflowExecutionResult(
            execution_id=execution_id,
            workflow_id=workflow_id,
            status=raw.get("status", "pending"),
            started_at=raw.get("started_at"),
            completed_at=raw.get("completed_at"),
            records=raw.get("records", []),
            error=raw.get("error"),
        )

    async def detect_forms(
        self, url: str, session_artifact_id: Optional[str] = None
    ) -> FormDetectionResult:
        """Async equivalent of FetchyrNamespace.detect_forms."""
        body: Dict[str, Any] = {"url": url}
        if session_artifact_id:
            body["session_artifact_id"] = session_artifact_id
        raw = await self._t.post("fetchyr/detect-forms", body)
        return FormDetectionResult(
            forms=raw.get("forms", []),
            total_forms=raw.get("total_forms", 0),
            error=raw.get("error"),
        )

    async def detect_mfa(
        self, url: str, session_artifact_id: Optional[str] = None
    ) -> MfaDetectionResult:
        """Async equivalent of FetchyrNamespace.detect_mfa."""
        body: Dict[str, Any] = {"url": url}
        if session_artifact_id:
            body["session_artifact_id"] = session_artifact_id
        raw = await self._t.post("fetchyr/detect-mfa", body)
        return MfaDetectionResult(
            mfa_detected=raw.get("mfa_detected", False),
            challenge_id=raw.get("challenge_id"),
            mfa_type=raw.get("mfa_type"),
            error=raw.get("error"),
        )

    async def submit_mfa(self, challenge_id: str, code: str) -> MfaResult:
        """Async equivalent of FetchyrNamespace.submit_mfa."""
        raw = await self._t.post("fetchyr/submit-mfa", {
            "challenge_id": challenge_id,
            "code": code,
        })
        return MfaResult(
            success=raw.get("success", False),
            session_artifact_id=raw.get("session_artifact_id"),
            error=raw.get("error"),
        )

    async def check_duplicates(
        self, records: List[Dict[str, Any]], domain: Optional[str] = None
    ) -> DeduplicationResult:
        """Async equivalent of FetchyrNamespace.check_duplicates."""
        body: Dict[str, Any] = {"records": records}
        if domain:
            body["domain"] = domain
        raw = await self._t.post("fetchyr/deduplicate", body)
        return DeduplicationResult(
            unique_records=raw.get("unique_records", []),
            duplicate_count=raw.get("duplicate_count", 0),
            total_input=raw.get("total_input", len(records)),
            error=raw.get("error"),
        )
