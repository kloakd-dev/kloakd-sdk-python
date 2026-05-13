"""
KLOAKD SDK — Nexus module namespace.

Nexus is the Strategy Engine — a 5-layer cognitive pipeline that analyses
page structure, synthesises an extraction strategy, verifies safety, executes
it, and learns from the result.

Most users call client.kolektr.page() which orchestrates Nexus internally.
Advanced users can call each layer directly for custom pipelines.

Layers::
    analyze()    → Perception  — understand the page
    synthesize() → Synthesis   — generate extraction code
    verify()     → Verification — safety-check the strategy
    execute()    → Execution   — run the strategy
    knowledge()  → Knowledge   — learn from execution
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Optional

from kloakd.models import (
    NexusAnalyzeResult,
    NexusExecuteResult,
    NexusKnowledgeResult,
    NexusSynthesisResult,
    NexusVerifyResult,
)

if TYPE_CHECKING:
    from kloakd._http import _AsyncHttpTransport, _HttpTransport


class NexusNamespace:
    """Synchronous Nexus operations. Access via ``client.nexus``."""

    def __init__(self, transport: "_HttpTransport") -> None:
        self._t = transport

    def analyze(
        self,
        url: str,
        html: str = "",
        constraints: Optional[Dict[str, Any]] = None,
    ) -> NexusAnalyzeResult:
        """
        Perception layer — analyse page structure and determine extraction strategy.

        Args:
            url: Target URL.
            html: Optional pre-fetched HTML (skips re-fetch when provided).
            constraints: Optional extraction constraints (fields to extract, etc.)

        Returns:
            NexusAnalyzeResult with perception_id, strategy, page_type.
        """
        body: Dict[str, Any] = {"url": url, "html": html}
        if constraints:
            body["constraints"] = constraints

        raw = self._t.post("nexus/analyze", body)
        return NexusAnalyzeResult(
            perception_id=raw.get("perception_id", ""),
            strategy=raw.get("strategy", {}),
            page_type=raw.get("page_type", "unknown"),
            complexity_level=raw.get("complexity_level", "unknown"),
            artifact_id=raw.get("artifact_id"),
            duration_ms=raw.get("duration_ms", 0),
            error=raw.get("error"),
        )

    def synthesize(
        self,
        perception_id: str,
        strategy: Optional[Dict[str, Any]] = None,
        timeout: int = 90,
    ) -> NexusSynthesisResult:
        """
        Synthesis layer — generate executable extraction code from a strategy.

        Args:
            perception_id: ID returned by analyze().
            strategy: Optional strategy override.
            timeout: Synthesis timeout in seconds. Default 90.

        Returns:
            NexusSynthesisResult with strategy_id and generated_code.
        """
        body: Dict[str, Any] = {"perception_id": perception_id, "timeout": timeout}
        if strategy:
            body["strategy"] = strategy

        raw = self._t.post("nexus/synthesize", body)
        return NexusSynthesisResult(
            strategy_id=raw.get("strategy_id", ""),
            strategy_name=raw.get("strategy_name", ""),
            generated_code=raw.get("generated_code", ""),
            artifact_id=raw.get("artifact_id"),
            synthesis_time_ms=raw.get("synthesis_time_ms", 0),
            error=raw.get("error"),
        )

    def verify(self, strategy_id: str) -> NexusVerifyResult:
        """
        Verification layer — safety-check a synthesised strategy.

        Args:
            strategy_id: ID returned by synthesize().

        Returns:
            NexusVerifyResult with is_safe, risk_score, violations.
        """
        raw = self._t.post("nexus/verify", {"strategy_id": strategy_id})
        return NexusVerifyResult(
            verification_result_id=raw.get("verification_result_id", ""),
            is_safe=raw.get("is_safe", False),
            risk_score=raw.get("risk_score", 0.0),
            safety_score=raw.get("safety_score", 1.0),
            violations=raw.get("violations", []),
            duration_ms=raw.get("duration_ms", 0),
            error=raw.get("error"),
        )

    def execute(self, strategy_id: str, url: str) -> NexusExecuteResult:
        """
        Execution layer — run a verified strategy against a URL.

        Args:
            strategy_id: ID returned by synthesize().
            url: Target URL to run the strategy against.

        Returns:
            NexusExecuteResult with records and execution_result_id.
        """
        raw = self._t.post("nexus/execute", {"strategy_id": strategy_id, "url": url})
        return NexusExecuteResult(
            execution_result_id=raw.get("execution_result_id", ""),
            success=raw.get("success", False),
            records=raw.get("data", []),
            artifact_id=raw.get("artifact_id"),
            duration_ms=raw.get("duration_ms", 0),
            error=raw.get("error"),
        )

    def knowledge(
        self,
        execution_result_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> NexusKnowledgeResult:
        """
        Knowledge layer — learn from an execution result.

        Args:
            execution_result_id: ID returned by execute().
            limit: Max concepts/patterns per response.
            offset: Pagination offset.

        Returns:
            NexusKnowledgeResult with learned_concepts and learned_patterns.
        """
        raw = self._t.post("nexus/knowledge", {
            "execution_result_id": execution_result_id,
            "limit": limit,
            "offset": offset,
        })
        return NexusKnowledgeResult(
            learned_concepts=raw.get("learned_concepts", []),
            learned_patterns=raw.get("learned_patterns", []),
            has_more=raw.get("has_more", False),
            total=raw.get("total", 0),
            duration_ms=raw.get("duration_ms", 0),
            error=raw.get("error"),
        )

    def reason(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Perform logical reasoning via the Strategy Engine.

        Args:
            context: Reasoning context with problem definition.

        Returns:
            Dict with reasoning result.
        """
        return self._t.post("nexus/reason", context)

    # ── Recommendations ───────────────────────────────────────────────

    def recommend_analyze(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze and get recommendations."""
        return self._t.post("nexus/recommendations/analyze", data)

    def list_recommendation_applications(self) -> Dict[str, Any]:
        """List recommendation applications."""
        return self._t.get("nexus/recommendations/applications")

    def get_cache_statistics(self) -> Dict[str, Any]:
        """Get recommendation cache statistics."""
        return self._t.get("nexus/recommendations/cache/statistics")

    def cleanup_cache(self) -> Dict[str, Any]:
        """Cleanup recommendation cache."""
        return self._t.post("nexus/recommendations/cache/cleanup", {})

    def invalidate_cache(self) -> Dict[str, Any]:
        """Invalidate recommendation cache."""
        return self._t.post("nexus/recommendations/cache/invalidate", {})

    def get_hooks_status(self) -> Dict[str, Any]:
        """Get hooks status."""
        return self._t.get("nexus/recommendations/hooks/status")

    def enable_hook(self, hook_name: str) -> Dict[str, Any]:
        """Enable a recommendation hook."""
        return self._t.post(f"nexus/recommendations/hooks/{hook_name}/enable", {})

    def disable_hook(self, hook_name: str) -> Dict[str, Any]:
        """Disable a recommendation hook."""
        return self._t.post(f"nexus/recommendations/hooks/{hook_name}/disable", {})

    def create_preference(self, preference: Dict[str, Any]) -> Dict[str, Any]:
        """Create a recommendation preference."""
        return self._t.post("nexus/recommendations/preferences", preference)

    def get_preferences(self, user_id: str) -> Dict[str, Any]:
        """Get user preferences."""
        return self._t.get(f"nexus/recommendations/preferences/{user_id}")

    def update_preference(self, preference_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Update a recommendation preference."""
        return self._t.put(f"nexus/recommendations/preferences/{preference_id}", data)

    def delete_preference(self, preference_id: str) -> None:
        """Delete a recommendation preference."""
        self._t.delete(f"nexus/recommendations/preferences/{preference_id}")

    def get_recommendation_statistics(self) -> Dict[str, Any]:
        """Get recommendation statistics."""
        return self._t.get("nexus/recommendations/statistics")


class AsyncNexusNamespace:
    """Async Nexus operations. Access via ``async_client.nexus``."""

    def __init__(self, transport: "_AsyncHttpTransport") -> None:
        self._t = transport

    async def analyze(
        self,
        url: str,
        html: str = "",
        constraints: Optional[Dict[str, Any]] = None,
    ) -> NexusAnalyzeResult:
        """Async equivalent of NexusNamespace.analyze."""
        body: Dict[str, Any] = {"url": url, "html": html}
        if constraints:
            body["constraints"] = constraints
        raw = await self._t.post("nexus/analyze", body)
        return NexusAnalyzeResult(
            perception_id=raw.get("perception_id", ""),
            strategy=raw.get("strategy", {}),
            page_type=raw.get("page_type", "unknown"),
            complexity_level=raw.get("complexity_level", "unknown"),
            artifact_id=raw.get("artifact_id"),
            duration_ms=raw.get("duration_ms", 0),
            error=raw.get("error"),
        )

    async def synthesize(
        self,
        perception_id: str,
        strategy: Optional[Dict[str, Any]] = None,
        timeout: int = 90,
    ) -> NexusSynthesisResult:
        """Async equivalent of NexusNamespace.synthesize."""
        body: Dict[str, Any] = {"perception_id": perception_id, "timeout": timeout}
        if strategy:
            body["strategy"] = strategy
        raw = await self._t.post("nexus/synthesize", body)
        return NexusSynthesisResult(
            strategy_id=raw.get("strategy_id", ""),
            strategy_name=raw.get("strategy_name", ""),
            generated_code=raw.get("generated_code", ""),
            artifact_id=raw.get("artifact_id"),
            synthesis_time_ms=raw.get("synthesis_time_ms", 0),
            error=raw.get("error"),
        )

    async def verify(self, strategy_id: str) -> NexusVerifyResult:
        """Async equivalent of NexusNamespace.verify."""
        raw = await self._t.post("nexus/verify", {"strategy_id": strategy_id})
        return NexusVerifyResult(
            verification_result_id=raw.get("verification_result_id", ""),
            is_safe=raw.get("is_safe", False),
            risk_score=raw.get("risk_score", 0.0),
            safety_score=raw.get("safety_score", 1.0),
            violations=raw.get("violations", []),
            duration_ms=raw.get("duration_ms", 0),
            error=raw.get("error"),
        )

    async def execute(self, strategy_id: str, url: str) -> NexusExecuteResult:
        """Async equivalent of NexusNamespace.execute."""
        raw = await self._t.post("nexus/execute", {"strategy_id": strategy_id, "url": url})
        return NexusExecuteResult(
            execution_result_id=raw.get("execution_result_id", ""),
            success=raw.get("success", False),
            records=raw.get("data", []),
            artifact_id=raw.get("artifact_id"),
            duration_ms=raw.get("duration_ms", 0),
            error=raw.get("error"),
        )

    async def knowledge(
        self,
        execution_result_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> NexusKnowledgeResult:
        """Async equivalent of NexusNamespace.knowledge."""
        raw = await self._t.post("nexus/knowledge", {
            "execution_result_id": execution_result_id,
            "limit": limit,
            "offset": offset,
        })
        return NexusKnowledgeResult(
            learned_concepts=raw.get("learned_concepts", []),
            learned_patterns=raw.get("learned_patterns", []),
            has_more=raw.get("has_more", False),
            total=raw.get("total", 0),
            duration_ms=raw.get("duration_ms", 0),
            error=raw.get("error"),
        )

    async def reason(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Async equivalent of NexusNamespace.reason."""
        return await self._t.post("nexus/reason", context)

    async def recommend_analyze(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Async equivalent of NexusNamespace.recommend_analyze."""
        return await self._t.post("nexus/recommendations/analyze", data)

    async def list_recommendation_applications(self) -> Dict[str, Any]:
        """Async equivalent of NexusNamespace.list_recommendation_applications."""
        return await self._t.get("nexus/recommendations/applications")

    async def get_cache_statistics(self) -> Dict[str, Any]:
        """Async equivalent of NexusNamespace.get_cache_statistics."""
        return await self._t.get("nexus/recommendations/cache/statistics")

    async def cleanup_cache(self) -> Dict[str, Any]:
        """Async equivalent of NexusNamespace.cleanup_cache."""
        return await self._t.post("nexus/recommendations/cache/cleanup", {})

    async def invalidate_cache(self) -> Dict[str, Any]:
        """Async equivalent of NexusNamespace.invalidate_cache."""
        return await self._t.post("nexus/recommendations/cache/invalidate", {})

    async def get_hooks_status(self) -> Dict[str, Any]:
        """Async equivalent of NexusNamespace.get_hooks_status."""
        return await self._t.get("nexus/recommendations/hooks/status")

    async def enable_hook(self, hook_name: str) -> Dict[str, Any]:
        """Async equivalent of NexusNamespace.enable_hook."""
        return await self._t.post(f"nexus/recommendations/hooks/{hook_name}/enable", {})

    async def disable_hook(self, hook_name: str) -> Dict[str, Any]:
        """Async equivalent of NexusNamespace.disable_hook."""
        return await self._t.post(f"nexus/recommendations/hooks/{hook_name}/disable", {})

    async def create_preference(self, preference: Dict[str, Any]) -> Dict[str, Any]:
        """Async equivalent of NexusNamespace.create_preference."""
        return await self._t.post("nexus/recommendations/preferences", preference)

    async def get_preferences(self, user_id: str) -> Dict[str, Any]:
        """Async equivalent of NexusNamespace.get_preferences."""
        return await self._t.get(f"nexus/recommendations/preferences/{user_id}")

    async def update_preference(self, preference_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Async equivalent of NexusNamespace.update_preference."""
        return await self._t.put(f"nexus/recommendations/preferences/{preference_id}", data)

    async def delete_preference(self, preference_id: str) -> None:
        """Async equivalent of NexusNamespace.delete_preference."""
        await self._t.delete(f"nexus/recommendations/preferences/{preference_id}")

    async def get_recommendation_statistics(self) -> Dict[str, Any]:
        """Async equivalent of NexusNamespace.get_recommendation_statistics."""
        return await self._t.get("nexus/recommendations/statistics")
