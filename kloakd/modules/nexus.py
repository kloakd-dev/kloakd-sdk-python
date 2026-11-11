"""
KLOAKD SDK — Nexus module namespace.

Nexus is the strategy layer: analyse a page, synthesise an extraction
program and verify it.

Usage::

    page = client.evadr.fetch("https://example.com/products")
    analysis = client.nexus.analyze(page.url, page.html or "")
    program = client.nexus.synthesize(page.url, page.html or "", goal="product names and prices")
    check = client.nexus.verify(program.strategy_id)
    print(check.verified, check.status, check.risk_score)

``analyze`` and ``synthesize`` may be handed off as a job (HTTP 202, after
about 85 s); the SDK follows it to the same result.

``execute`` and ``knowledge`` were removed after 0.6.0: the API removed
``POST nexus/execute``, and ``nexus/knowledge`` is not part of the public
API (kobe-scraper scripts/generate_public_openapi.py EXCLUDED).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

from kloakd.models import (
    NexusAnalyzeResult,
    NexusSafetyCheck,
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
        )

    return parse


def _verification(strategy_id: str) -> Callable[[Dict[str, Any]], NexusVerifyResult]:
    def parse(raw: Dict[str, Any]) -> NexusVerifyResult:
        return NexusVerifyResult(
            strategy_id=str(raw.get("strategy_id") or strategy_id),
            verified=bool(raw.get("verified", False)),
            safety_score=float(raw.get("safety_score") or 0.0),
            violations=raw.get("violations") or [],
            status=raw.get("status"),
            risk_score=float(raw.get("risk_score") or 0.0),
            safety_checks=[
                NexusSafetyCheck(
                    property=str(c.get("property") or ""),
                    passed=bool(c.get("passed", False)),
                    details=str(c.get("details") or ""),
                )
                for c in raw.get("safety_checks") or []
                if isinstance(c, dict)
            ],
            verification_result_id=raw.get("verification_result_id"),
            duration_ms=int(raw.get("duration_ms") or 0),
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

    def reason(
        self,
        query_type: str,
        parameters: Optional[List[str]] = None,
        perception_id: Optional[str] = None,
        timeout_secs: Optional[float] = None,
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

    async def reason(
        self,
        query_type: str,
        parameters: Optional[List[str]] = None,
        perception_id: Optional[str] = None,
        timeout_secs: Optional[float] = None,
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

