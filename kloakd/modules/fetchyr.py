"""
KLOAKD SDK — Fetchyr module namespace.

Fetchyr handles authenticated access: stored credentials, logins that
produce a session artifact, forms, MFA, RPA workflows and deduplication.

Usage::

    client.fetchyr.store_credentials("acme", username="me", password="...")
    session = client.fetchyr.authenticate("acme", "https://acme.example/login")
    page = client.evadr.fetch("https://acme.example/account",
                              session_artifact_id=session.artifact_id)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

from kloakd.models import (
    DuplicateCheckResult,
    FormDetectionResult,
    MfaChallenge,
    MfaDetectionResult,
    SessionResult,
    WorkflowExecutionResult,
    WorkflowResult,
)
from kloakd.modules._ops import Op, _Op, arun, as_list, compact, run

if TYPE_CHECKING:
    from kloakd._http import _AsyncHttpTransport, _HttpTransport


def _session(target_url: str) -> Callable[[Dict[str, Any]], SessionResult]:
    def parse(raw: Dict[str, Any]) -> SessionResult:
        return SessionResult(
            success=bool(raw.get("success", False)),
            session_id=str(raw.get("session_id") or ""),
            url=target_url,
            artifact_id=raw.get("artifact_id"),
            target_domain=raw.get("target_domain"),
            auth_method=raw.get("auth_method"),
            error=raw.get("error"),
        )

    return parse


def _workflow(raw: Dict[str, Any]) -> WorkflowResult:
    return WorkflowResult(
        workflow_id=str(raw.get("id") or raw.get("workflow_id") or ""),
        name=str(raw.get("name") or ""),
        description=raw.get("description"),
        workflow_type=raw.get("workflow_type"),
        steps=raw.get("steps") or [],
        is_active=bool(raw.get("is_active", True)),
        created_at=str(raw.get("created_at") or ""),
        error=raw.get("error"),
    )


def _execution(raw: Dict[str, Any]) -> WorkflowExecutionResult:
    return WorkflowExecutionResult(
        execution_id=str(raw.get("execution_id") or ""),
        workflow_id=str(raw.get("workflow_id") or ""),
        status=str(raw.get("status") or "unknown"),
        started_at=raw.get("started_at"),
        completed_at=raw.get("completed_at"),
        result=raw.get("result"),
        error=raw.get("error"),
    )


def _challenge(raw: Dict[str, Any]) -> MfaChallenge:
    return MfaChallenge(
        id=str(raw.get("id") or ""),
        status=str(raw.get("status") or ""),
        session_id=raw.get("session_id"),
        mfa_type=raw.get("mfa_type"),
        challenge_data=raw.get("challenge_data") or {},
        expires_at=raw.get("expires_at"),
        created_at=raw.get("created_at"),
    )


def _challenges(raw: Any) -> List[MfaChallenge]:
    return [_challenge(c) for c in raw] if isinstance(raw, list) else []


def _forms(url: str) -> Callable[[Dict[str, Any]], FormDetectionResult]:
    def parse(raw: Dict[str, Any]) -> FormDetectionResult:
        return FormDetectionResult(
            url=raw.get("url", url),
            forms=raw.get("fields") or [],
            total_forms=int(raw.get("forms_found") or 0),
            login_form_detected=bool(raw.get("login_form_detected", False)),
            error=raw.get("error"),
        )

    return parse


def _mfa(raw: Dict[str, Any]) -> MfaDetectionResult:
    return MfaDetectionResult(
        mfa_detected=bool(raw.get("mfa_detected", False)),
        challenge_id=raw.get("challenge_id"),
        mfa_type=raw.get("mfa_type"),
        message=raw.get("message"),
        error=raw.get("error"),
    )


def _duplicate(raw: Dict[str, Any]) -> DuplicateCheckResult:
    score = raw.get("similarity_score")
    return DuplicateCheckResult(
        is_duplicate=bool(raw.get("is_duplicate", False)),
        original_url=raw.get("original_url"),
        similarity_score=float(score) if score is not None else None,
        match_type=raw.get("match_type"),
    )


# ── Operations ────────────────────────────────────────────────────────────


def _authenticate(credential_name: str, target_url: str) -> "Op[SessionResult]":
    return _Op(
        "POST",
        "fetchyr/authenticate",
        {"credential_name": credential_name, "target_url": target_url},
        parse=_session(target_url),
    )


def _store_credentials(
    name: str, username: str, password: str, extra: Optional[Dict[str, Any]]
) -> "Op[Dict[str, Any]]":
    return _Op(
        "POST",
        "fetchyr/account/credentials",
        compact(
            {"name": name, "username": username, "password": password, "extra": extra}
        ),
    )


def _create_workflow(
    name: str,
    steps: List[Dict[str, Any]],
    description: Optional[str],
    workflow_type: Optional[str],
) -> "Op[WorkflowResult]":
    return _Op(
        "POST",
        "fetchyr/workflows",
        compact(
            {
                "name": name,
                "steps": steps,
                "description": description,
                "workflow_type": workflow_type,
            }
        ),
        parse=_workflow,
    )


def _execute_workflow(
    workflow_id: str,
    target_url: str,
    session_artifact_id: Optional[str],
    input_data: Optional[Dict[str, Any]],
) -> "Op[WorkflowExecutionResult]":
    return _Op(
        "POST",
        f"fetchyr/workflows/{workflow_id}/execute",
        compact(
            {
                "target_url": target_url,
                "session_artifact_id": session_artifact_id,
                "input_data": input_data,
            }
        ),
        parse=_execution,
    )


def _update_workflow(
    workflow_id: str,
    name: Optional[str],
    description: Optional[str],
    steps: Optional[List[Dict[str, Any]]],
    is_active: Optional[bool],
) -> "Op[WorkflowResult]":
    return _Op(
        "PATCH",
        f"fetchyr/workflows/{workflow_id}",
        compact(
            {
                "name": name,
                "description": description,
                "steps": steps,
                "is_active": is_active,
            }
        ),
        parse=_workflow,
    )


def _create_multi_site(
    name: str,
    sites: List[Dict[str, Any]],
    description: Optional[str],
    dependencies: Optional[Dict[str, Any]],
    global_config: Optional[Dict[str, Any]],
) -> "Op[Dict[str, Any]]":
    return _Op(
        "POST",
        "fetchyr/multi-site-workflows",
        compact(
            {
                "name": name,
                "sites": sites,
                "description": description,
                "dependencies": dependencies,
                "global_config": global_config,
            }
        ),
    )


def _url_body(url: str, session_artifact_id: Optional[str]) -> Dict[str, Any]:
    return compact({"url": url, "session_artifact_id": session_artifact_id})


class FetchyrNamespace:
    """Synchronous Fetchyr operations. Access via ``client.fetchyr``."""

    def __init__(self, transport: "_HttpTransport") -> None:
        self._t = transport

    def authenticate(self, credential_name: str, target_url: str) -> SessionResult:
        """Log in with credentials stored under ``credential_name``; returns the session artifact."""
        return run(self._t, _authenticate(credential_name, target_url))

    def store_credentials(
        self,
        name: str,
        username: str,
        password: str,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Store login credentials (encrypted server-side) for authenticate()."""
        return run(self._t, _store_credentials(name, username, password, extra))

    def list_credentials(self) -> List[Dict[str, Any]]:
        return run(self._t, _Op("GET", "fetchyr/account/credentials", parse=as_list))

    def delete_credentials(self, name: str) -> None:
        run(self._t, _Op("DELETE", f"fetchyr/account/credentials/{name}"))

    def list_sessions(self) -> List[Dict[str, Any]]:
        return run(self._t, _Op("GET", "fetchyr/sessions", parse=as_list))

    def invalidate_session(self, artifact_id: str) -> None:
        run(self._t, _Op("DELETE", f"fetchyr/sessions/{artifact_id}"))

    def terminate_session(self, artifact_id: str) -> None:
        """Alias of invalidate_session."""
        self.invalidate_session(artifact_id)

    def create_workflow(
        self,
        name: str,
        steps: List[Dict[str, Any]],
        description: Optional[str] = None,
        workflow_type: Optional[str] = None,
    ) -> WorkflowResult:
        return run(self._t, _create_workflow(name, steps, description, workflow_type))

    def execute_workflow(
        self,
        workflow_id: str,
        target_url: str,
        session_artifact_id: Optional[str] = None,
        input_data: Optional[Dict[str, Any]] = None,
    ) -> WorkflowExecutionResult:
        return run(
            self._t,
            _execute_workflow(workflow_id, target_url, session_artifact_id, input_data),
        )

    def get_execution(
        self, workflow_id: str, execution_id: str
    ) -> WorkflowExecutionResult:
        return run(
            self._t,
            _Op(
                "GET",
                f"fetchyr/workflows/{workflow_id}/executions/{execution_id}",
                parse=_execution,
            ),
        )

    def resume_execution(
        self, workflow_id: str, execution_id: str, body: Optional[Dict[str, Any]] = None
    ) -> WorkflowExecutionResult:
        """Resume an execution paused for intervention (for example MFA)."""
        return run(
            self._t,
            _Op(
                "POST",
                f"fetchyr/workflows/{workflow_id}/executions/{execution_id}/resume",
                body or {},
                parse=_execution,
            ),
        )

    def list_workflows(self) -> Dict[str, Any]:
        return run(self._t, _Op("GET", "fetchyr/workflows"))

    def get_workflow(self, workflow_id: str) -> WorkflowResult:
        return run(
            self._t, _Op("GET", f"fetchyr/workflows/{workflow_id}", parse=_workflow)
        )

    def update_workflow(
        self,
        workflow_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        steps: Optional[List[Dict[str, Any]]] = None,
        is_active: Optional[bool] = None,
    ) -> WorkflowResult:
        return run(
            self._t, _update_workflow(workflow_id, name, description, steps, is_active)
        )

    def delete_workflow(self, workflow_id: str) -> None:
        run(self._t, _Op("DELETE", f"fetchyr/workflows/{workflow_id}"))

    def get_workflow_statistics(self, workflow_id: str) -> Dict[str, Any]:
        return run(self._t, _Op("GET", f"fetchyr/workflows/{workflow_id}/statistics"))

    def create_multi_site_workflow(
        self,
        name: str,
        sites: List[Dict[str, Any]],
        description: Optional[str] = None,
        dependencies: Optional[Dict[str, Any]] = None,
        global_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return run(
            self._t,
            _create_multi_site(name, sites, description, dependencies, global_config),
        )

    def detect_forms(
        self, url: str, session_artifact_id: Optional[str] = None
    ) -> FormDetectionResult:
        return run(
            self._t,
            _Op(
                "POST",
                "fetchyr/form/detect",
                _url_body(url, session_artifact_id),
                parse=_forms(url),
            ),
        )

    def fill_form(
        self,
        url: str,
        form_data: Dict[str, str],
        session_artifact_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        return run(
            self._t,
            _Op(
                "POST",
                "fetchyr/form/fill",
                compact(
                    {
                        "url": url,
                        "form_data": form_data,
                        "session_artifact_id": session_artifact_id,
                    }
                ),
            ),
        )

    def detect_mfa(
        self, url: str, session_artifact_id: Optional[str] = None
    ) -> MfaDetectionResult:
        return run(
            self._t,
            _Op(
                "POST",
                "fetchyr/mfa/detect",
                _url_body(url, session_artifact_id),
                parse=_mfa,
            ),
        )

    def submit_mfa(self, challenge_id: str, resolution: str) -> MfaChallenge:
        """Resolve a queued MFA challenge with the code (or other resolution) the user supplied."""
        return run(
            self._t,
            _Op(
                "POST",
                f"fetchyr/mfa-queue/{challenge_id}/resolve",
                {"resolution": resolution},
                parse=_challenge,
            ),
        )

    def list_mfa_challenges(self) -> List[MfaChallenge]:
        return run(self._t, _Op("GET", "fetchyr/mfa-queue", parse=_challenges))

    def get_mfa_challenge(self, challenge_id: str) -> MfaChallenge:
        return run(
            self._t,
            _Op("GET", f"fetchyr/mfa/challenges/{challenge_id}", parse=_challenge),
        )

    def get_mfa_statistics(self, domain: str) -> Dict[str, Any]:
        return run(self._t, _Op("GET", f"fetchyr/mfa/statistics/{domain}"))

    def check_duplicate(
        self,
        url: str,
        content_hash: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> DuplicateCheckResult:
        """Whether a URL (or content hash) was already seen in a deduplication session."""
        return run(
            self._t,
            _Op(
                "POST",
                "fetchyr/deduplication/check",
                compact(
                    {"url": url, "content_hash": content_hash, "session_id": session_id}
                ),
                parse=_duplicate,
            ),
        )

    def create_dedup_session(
        self, name: str, strategy: Optional[str] = None
    ) -> Dict[str, Any]:
        return run(
            self._t,
            _Op(
                "POST",
                "fetchyr/deduplication/sessions",
                compact({"name": name, "strategy": strategy}),
            ),
        )

    def list_dedup_sessions(self) -> List[Dict[str, Any]]:
        return run(
            self._t, _Op("GET", "fetchyr/deduplication/sessions/active", parse=as_list)
        )

    def get_dedup_session(self, session_id: str) -> Dict[str, Any]:
        return run(self._t, _Op("GET", f"fetchyr/deduplication/sessions/{session_id}"))

    def get_dedup_session_statistics(self, session_id: str) -> Dict[str, Any]:
        return run(
            self._t,
            _Op("GET", f"fetchyr/deduplication/sessions/{session_id}/statistics"),
        )

    def get_dedup_domain_statistics(self, domain: str) -> Dict[str, Any]:
        return run(self._t, _Op("GET", f"fetchyr/deduplication/statistics/{domain}"))

    def discover_auth_chain(self, body: Dict[str, Any]) -> Dict[str, Any]:
        """Start an auth-chain discovery (a login flow that may need user input)."""
        return run(self._t, _Op("POST", "fetchyr/auth-chain/discover", body))

    def get_auth_chain_status(self, discovery_id: str) -> Dict[str, Any]:
        return run(self._t, _Op("GET", f"fetchyr/auth-chain/{discovery_id}/status"))

    def resume_auth_chain_credentials(
        self, discovery_id: str, body: Dict[str, Any]
    ) -> Dict[str, Any]:
        return run(
            self._t,
            _Op("POST", f"fetchyr/auth-chain/{discovery_id}/resume-credentials", body),
        )

    def resume_auth_chain_mfa(
        self, discovery_id: str, body: Dict[str, Any]
    ) -> Dict[str, Any]:
        return run(
            self._t, _Op("POST", f"fetchyr/auth-chain/{discovery_id}/resume-mfa", body)
        )


class AsyncFetchyrNamespace:
    """Async Fetchyr operations. Access via ``async_client.fetchyr``."""

    def __init__(self, transport: "_AsyncHttpTransport") -> None:
        self._t = transport

    async def authenticate(
        self, credential_name: str, target_url: str
    ) -> SessionResult:
        return await arun(self._t, _authenticate(credential_name, target_url))

    async def store_credentials(
        self,
        name: str,
        username: str,
        password: str,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return await arun(self._t, _store_credentials(name, username, password, extra))

    async def list_credentials(self) -> List[Dict[str, Any]]:
        return await arun(
            self._t, _Op("GET", "fetchyr/account/credentials", parse=as_list)
        )

    async def delete_credentials(self, name: str) -> None:
        await arun(self._t, _Op("DELETE", f"fetchyr/account/credentials/{name}"))

    async def list_sessions(self) -> List[Dict[str, Any]]:
        return await arun(self._t, _Op("GET", "fetchyr/sessions", parse=as_list))

    async def invalidate_session(self, artifact_id: str) -> None:
        await arun(self._t, _Op("DELETE", f"fetchyr/sessions/{artifact_id}"))

    async def terminate_session(self, artifact_id: str) -> None:
        await self.invalidate_session(artifact_id)

    async def create_workflow(
        self,
        name: str,
        steps: List[Dict[str, Any]],
        description: Optional[str] = None,
        workflow_type: Optional[str] = None,
    ) -> WorkflowResult:
        return await arun(
            self._t, _create_workflow(name, steps, description, workflow_type)
        )

    async def execute_workflow(
        self,
        workflow_id: str,
        target_url: str,
        session_artifact_id: Optional[str] = None,
        input_data: Optional[Dict[str, Any]] = None,
    ) -> WorkflowExecutionResult:
        return await arun(
            self._t,
            _execute_workflow(workflow_id, target_url, session_artifact_id, input_data),
        )

    async def get_execution(
        self, workflow_id: str, execution_id: str
    ) -> WorkflowExecutionResult:
        return await arun(
            self._t,
            _Op(
                "GET",
                f"fetchyr/workflows/{workflow_id}/executions/{execution_id}",
                parse=_execution,
            ),
        )

    async def resume_execution(
        self, workflow_id: str, execution_id: str, body: Optional[Dict[str, Any]] = None
    ) -> WorkflowExecutionResult:
        return await arun(
            self._t,
            _Op(
                "POST",
                f"fetchyr/workflows/{workflow_id}/executions/{execution_id}/resume",
                body or {},
                parse=_execution,
            ),
        )

    async def list_workflows(self) -> Dict[str, Any]:
        return await arun(self._t, _Op("GET", "fetchyr/workflows"))

    async def get_workflow(self, workflow_id: str) -> WorkflowResult:
        return await arun(
            self._t, _Op("GET", f"fetchyr/workflows/{workflow_id}", parse=_workflow)
        )

    async def update_workflow(
        self,
        workflow_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        steps: Optional[List[Dict[str, Any]]] = None,
        is_active: Optional[bool] = None,
    ) -> WorkflowResult:
        return await arun(
            self._t, _update_workflow(workflow_id, name, description, steps, is_active)
        )

    async def delete_workflow(self, workflow_id: str) -> None:
        await arun(self._t, _Op("DELETE", f"fetchyr/workflows/{workflow_id}"))

    async def get_workflow_statistics(self, workflow_id: str) -> Dict[str, Any]:
        return await arun(
            self._t, _Op("GET", f"fetchyr/workflows/{workflow_id}/statistics")
        )

    async def create_multi_site_workflow(
        self,
        name: str,
        sites: List[Dict[str, Any]],
        description: Optional[str] = None,
        dependencies: Optional[Dict[str, Any]] = None,
        global_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return await arun(
            self._t,
            _create_multi_site(name, sites, description, dependencies, global_config),
        )

    async def detect_forms(
        self, url: str, session_artifact_id: Optional[str] = None
    ) -> FormDetectionResult:
        return await arun(
            self._t,
            _Op(
                "POST",
                "fetchyr/form/detect",
                _url_body(url, session_artifact_id),
                parse=_forms(url),
            ),
        )

    async def fill_form(
        self,
        url: str,
        form_data: Dict[str, str],
        session_artifact_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        return await arun(
            self._t,
            _Op(
                "POST",
                "fetchyr/form/fill",
                compact(
                    {
                        "url": url,
                        "form_data": form_data,
                        "session_artifact_id": session_artifact_id,
                    }
                ),
            ),
        )

    async def detect_mfa(
        self, url: str, session_artifact_id: Optional[str] = None
    ) -> MfaDetectionResult:
        return await arun(
            self._t,
            _Op(
                "POST",
                "fetchyr/mfa/detect",
                _url_body(url, session_artifact_id),
                parse=_mfa,
            ),
        )

    async def submit_mfa(self, challenge_id: str, resolution: str) -> MfaChallenge:
        return await arun(
            self._t,
            _Op(
                "POST",
                f"fetchyr/mfa-queue/{challenge_id}/resolve",
                {"resolution": resolution},
                parse=_challenge,
            ),
        )

    async def list_mfa_challenges(self) -> List[MfaChallenge]:
        return await arun(self._t, _Op("GET", "fetchyr/mfa-queue", parse=_challenges))

    async def get_mfa_challenge(self, challenge_id: str) -> MfaChallenge:
        return await arun(
            self._t,
            _Op("GET", f"fetchyr/mfa/challenges/{challenge_id}", parse=_challenge),
        )

    async def get_mfa_statistics(self, domain: str) -> Dict[str, Any]:
        return await arun(self._t, _Op("GET", f"fetchyr/mfa/statistics/{domain}"))

    async def check_duplicate(
        self,
        url: str,
        content_hash: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> DuplicateCheckResult:
        return await arun(
            self._t,
            _Op(
                "POST",
                "fetchyr/deduplication/check",
                compact(
                    {"url": url, "content_hash": content_hash, "session_id": session_id}
                ),
                parse=_duplicate,
            ),
        )

    async def create_dedup_session(
        self, name: str, strategy: Optional[str] = None
    ) -> Dict[str, Any]:
        return await arun(
            self._t,
            _Op(
                "POST",
                "fetchyr/deduplication/sessions",
                compact({"name": name, "strategy": strategy}),
            ),
        )

    async def list_dedup_sessions(self) -> List[Dict[str, Any]]:
        return await arun(
            self._t, _Op("GET", "fetchyr/deduplication/sessions/active", parse=as_list)
        )

    async def get_dedup_session(self, session_id: str) -> Dict[str, Any]:
        return await arun(
            self._t, _Op("GET", f"fetchyr/deduplication/sessions/{session_id}")
        )

    async def get_dedup_session_statistics(self, session_id: str) -> Dict[str, Any]:
        return await arun(
            self._t,
            _Op("GET", f"fetchyr/deduplication/sessions/{session_id}/statistics"),
        )

    async def get_dedup_domain_statistics(self, domain: str) -> Dict[str, Any]:
        return await arun(
            self._t, _Op("GET", f"fetchyr/deduplication/statistics/{domain}")
        )

    async def discover_auth_chain(self, body: Dict[str, Any]) -> Dict[str, Any]:
        return await arun(self._t, _Op("POST", "fetchyr/auth-chain/discover", body))

    async def get_auth_chain_status(self, discovery_id: str) -> Dict[str, Any]:
        return await arun(
            self._t, _Op("GET", f"fetchyr/auth-chain/{discovery_id}/status")
        )

    async def resume_auth_chain_credentials(
        self, discovery_id: str, body: Dict[str, Any]
    ) -> Dict[str, Any]:
        return await arun(
            self._t,
            _Op("POST", f"fetchyr/auth-chain/{discovery_id}/resume-credentials", body),
        )

    async def resume_auth_chain_mfa(
        self, discovery_id: str, body: Dict[str, Any]
    ) -> Dict[str, Any]:
        return await arun(
            self._t, _Op("POST", f"fetchyr/auth-chain/{discovery_id}/resume-mfa", body)
        )
