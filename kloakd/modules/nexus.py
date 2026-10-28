"""
KLOAKD SDK — Nexus module namespace.

Nexus is the strategy layer: analyse a page, synthesise an extraction
program, verify it, run it, and read what was learned.

Usage::

    page = client.evadr.fetch("https://example.com/products")
    analysis = client.nexus.analyze(page.url, page.html or "")
    program = client.nexus.synthesize(page.url, page.html or "", goal="product names and prices")
    if client.nexus.verify(program.strategy_id).ok:
        result = client.nexus.execute(program.strategy_id, page.url)
        if result.execution_result_id:
            learned = client.nexus.knowledge(result.execution_result_id)

``analyze``, ``synthesize`` and ``execute`` may be handed off as a job
(HTTP 202, after about 85 s); the SDK follows it to the same result.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

from kloakd.models import (
    NexusAnalyzeResult,
    NexusExecuteResult,
    NexusKnowledgeResult,
    NexusSynthesisResult,
    NexusVerifyResult,
)
from kloakd.modules._ops import _Op, arun, compact, run

if TYPE_CHECKING:
    from kloakd._http import _AsyncHttpTransport, _HttpTransport


def _artifact_id(raw: Dict[str, Any]) -> Optional[str]:
    artifact = raw.get("artifact")
    return (
        artifact.get("artifact_id")
        if isinstance(artifact, dict)
        else raw.get("artifact_id")
    )


def _analysis(url: str) -> Callable[[Dict[str, Any]], NexusAnalyzeResult]:
    def parse(raw: Dict[str, Any]) -> NexusAnalyzeResult:
        return NexusAnalyzeResult(
            url=raw.get("url", url),
            perception_id=str(raw.get("perception_id") or ""),
            reasoning_id=raw.get("reasoning_id"),
            strategy=raw.get("strategy") or {},
            page_type=raw.get("page_type") or "unknown",
            confidence=float(raw.get("confidence") or 0.0),
            artifact_id=_artifact_id(raw),
            error=raw.get("error"),
        )

    return parse


def _synthesis(url: str, goal: str) -> Callable[[Dict[str, Any]], NexusSynthesisResult]:
    def parse(raw: Dict[str, Any]) -> NexusSynthesisResult:
        return NexusSynthesisResult(
            url=raw.get("url", url),
            goal=raw.get("goal", goal),
            strategy_id=str(raw.get("strategy_id") or ""),
            strategy_name=str(raw.get("strategy_name") or ""),
            strategy_type=raw.get("strategy_type"),
            program=str(raw.get("program") or ""),
            steps=raw.get("steps") or [],
            confidence=float(raw.get("confidence") or 0.0),
            synthesis_time_ms=int(raw.get("synthesis_time_ms") or 0),
            error=raw.get("error"),
        )

    return parse


def _verification(strategy_id: str) -> Callable[[Dict[str, Any]], NexusVerifyResult]:
    def parse(raw: Dict[str, Any]) -> NexusVerifyResult:
        return NexusVerifyResult(
            strategy_id=str(raw.get("strategy_id") or strategy_id),
            verified=bool(raw.get("verified", False)),
            safety_score=float(raw.get("safety_score") or 0.0),
            violations=raw.get("violations") or [],
            error=raw.get("error"),
        )

    return parse


def _execution(
    strategy_id: str, url: str
) -> Callable[[Dict[str, Any]], NexusExecuteResult]:
    def parse(raw: Dict[str, Any]) -> NexusExecuteResult:
        return NexusExecuteResult(
            url=raw.get("url", url),
            strategy_id=str(raw.get("strategy_id") or strategy_id),
            success=bool(raw.get("success", False)),
            records=raw.get("records") or [],
            artifact_id=_artifact_id(raw),
            duration_ms=int(raw.get("duration_ms") or 0),
            error=raw.get("error_message"),
            execution_result_id=raw.get("execution_result_id"),
        )

    return parse


def _knowledge(
    execution_result_id: str,
) -> Callable[[Dict[str, Any]], NexusKnowledgeResult]:
    def parse(raw: Dict[str, Any]) -> NexusKnowledgeResult:
        return NexusKnowledgeResult(
            execution_result_id=str(
                raw.get("execution_result_id") or execution_result_id
            ),
            learned_concepts=raw.get("learned_concepts") or [],
            patterns=raw.get("patterns") or [],
            total_patterns=int(raw.get("total_patterns") or 0),
            duration_ms=int(raw.get("duration_ms") or 0),
            error=raw.get("error"),
        )

    return parse


class NexusNamespace:
    """Synchronous Nexus operations. Access via ``client.nexus``."""

    def __init__(self, transport: "_HttpTransport") -> None:
        self._t = transport

    def analyze(
        self, url: str, html: str, constraints: Optional[Dict[str, Any]] = None
    ) -> NexusAnalyzeResult:
        """Analyse a page (its URL and HTML) and propose an extraction strategy."""
        return run(
            self._t,
            _Op(
                "POST",
                "nexus/analyze",
                compact({"url": url, "html": html, "constraints": constraints}),
                parse=_analysis(url),
                follow=True,
            ),
        )

    def synthesize(self, url: str, html: str, goal: str) -> NexusSynthesisResult:
        """Generate an extraction program for a page and a goal."""
        return run(
            self._t,
            _Op(
                "POST",
                "nexus/synthesize",
                {"url": url, "html": html, "goal": goal},
                parse=_synthesis(url, goal),
                follow=True,
            ),
        )

    def verify(self, strategy_id: str) -> NexusVerifyResult:
        """Check a synthesised strategy's safety."""
        return run(
            self._t,
            _Op(
                "POST",
                "nexus/verify",
                {"strategy_id": strategy_id},
                parse=_verification(strategy_id),
            ),
        )

    def execute(
        self, strategy_id: str, url: str, options: Optional[Dict[str, Any]] = None
    ) -> NexusExecuteResult:
        """Run a strategy against a URL.

        The result's ``execution_result_id`` (when the API returns one) is
        the id to pass to ``knowledge``.
        """
        return run(
            self._t,
            _Op(
                "POST",
                "nexus/execute",
                compact({"strategy_id": strategy_id, "url": url, "options": options}),
                parse=_execution(strategy_id, url),
                follow=True,
            ),
        )

    def knowledge(self, execution_result_id: str) -> NexusKnowledgeResult:
        """What an execution taught the knowledge store.

        ``execution_result_id`` is the ``execution_result_id`` of the result
        ``execute`` returned.
        """
        return run(
            self._t,
            _Op(
                "POST",
                "nexus/knowledge",
                {"execution_result_id": execution_result_id},
                parse=_knowledge(execution_result_id),
            ),
        )

    def reason(
        self,
        query_type: str,
        parameters: Optional[List[str]] = None,
        perception_id: Optional[str] = None,
        timeout_secs: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Run a reasoning query (``query_type`` is required by the API;
        ``parameters`` is a list of strings, modules/nexus/router.py ReasonRequest)."""
        return run(
            self._t,
            _Op(
                "POST",
                "nexus/reason",
                compact(
                    {
                        "query_type": query_type,
                        "parameters": list(parameters or []),
                        "perception_id": perception_id,
                        "timeout_secs": timeout_secs,
                    }
                ),
            ),
        )


class AsyncNexusNamespace:
    """Async Nexus operations. Access via ``async_client.nexus``."""

    def __init__(self, transport: "_AsyncHttpTransport") -> None:
        self._t = transport

    async def analyze(
        self, url: str, html: str, constraints: Optional[Dict[str, Any]] = None
    ) -> NexusAnalyzeResult:
        """Analyse a page (its URL and HTML) and propose an extraction strategy."""
        return await arun(
            self._t,
            _Op(
                "POST",
                "nexus/analyze",
                compact({"url": url, "html": html, "constraints": constraints}),
                parse=_analysis(url),
                follow=True,
            ),
        )

    async def synthesize(self, url: str, html: str, goal: str) -> NexusSynthesisResult:
        """Generate an extraction program for a page and a goal."""
        return await arun(
            self._t,
            _Op(
                "POST",
                "nexus/synthesize",
                {"url": url, "html": html, "goal": goal},
                parse=_synthesis(url, goal),
                follow=True,
            ),
        )

    async def verify(self, strategy_id: str) -> NexusVerifyResult:
        """Check a synthesised strategy's safety."""
        return await arun(
            self._t,
            _Op(
                "POST",
                "nexus/verify",
                {"strategy_id": strategy_id},
                parse=_verification(strategy_id),
            ),
        )

    async def execute(
        self, strategy_id: str, url: str, options: Optional[Dict[str, Any]] = None
    ) -> NexusExecuteResult:
        """Run a strategy against a URL."""
        return await arun(
            self._t,
            _Op(
                "POST",
                "nexus/execute",
                compact({"strategy_id": strategy_id, "url": url, "options": options}),
                parse=_execution(strategy_id, url),
                follow=True,
            ),
        )

    async def knowledge(self, execution_result_id: str) -> NexusKnowledgeResult:
        """What an execution taught the knowledge store (the id is
        ``execution_result_id`` of the result ``execute`` returned)."""
        return await arun(
            self._t,
            _Op(
                "POST",
                "nexus/knowledge",
                {"execution_result_id": execution_result_id},
                parse=_knowledge(execution_result_id),
            ),
        )

    async def reason(
        self,
        query_type: str,
        parameters: Optional[List[str]] = None,
        perception_id: Optional[str] = None,
        timeout_secs: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Run a reasoning query (``query_type`` is required by the API;
        ``parameters`` is a list of strings, modules/nexus/router.py ReasonRequest)."""
        return await arun(
            self._t,
            _Op(
                "POST",
                "nexus/reason",
                compact(
                    {
                        "query_type": query_type,
                        "parameters": list(parameters or []),
                        "perception_id": perception_id,
                        "timeout_secs": timeout_secs,
                    }
                ),
            ),
        )

