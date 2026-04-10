"""Tests for the Nexus namespace — 5-layer cognitive pipeline."""

from __future__ import annotations

import pytest
import respx

from kloakd import (
    Kloakd,
    NexusAnalyzeResult,
    NexusExecuteResult,
    NexusKnowledgeResult,
    NexusSynthesisResult,
    NexusVerifyResult,
)
from tests.conftest import TEST_BASE_URL, TEST_ORG_ID, ORG_PREFIX, mock_response


@pytest.fixture
def client() -> Kloakd:
    return Kloakd(api_key="sk-test-key", organization_id=TEST_ORG_ID, base_url=TEST_BASE_URL)


@respx.mock
def test_analyze(client: Kloakd) -> None:
    respx.post(f"{TEST_BASE_URL}{ORG_PREFIX}/nexus/analyze").mock(
        return_value=mock_response({
            "perception_id": "perc-001",
            "strategy": {"type": "css_extraction"},
            "page_type": "listing",
            "complexity_level": "low",
            "artifact_id": "art-nexus-001",
            "duration_ms": 120,
            "error": None,
        })
    )
    result = client.nexus.analyze("https://example.com", html="<html>...</html>")
    assert isinstance(result, NexusAnalyzeResult)
    assert result.perception_id == "perc-001"
    assert result.page_type == "listing"
    assert result.complexity_level == "low"
    assert result.ok is True


@respx.mock
def test_analyze_with_constraints(client: Kloakd) -> None:
    route = respx.post(f"{TEST_BASE_URL}{ORG_PREFIX}/nexus/analyze")
    route.mock(return_value=mock_response({
        "perception_id": "perc-002",
        "strategy": {},
        "page_type": "detail",
        "complexity_level": "medium",
        "artifact_id": None,
        "duration_ms": 200,
        "error": None,
    }))
    result = client.nexus.analyze(
        "https://example.com",
        constraints={"fields": ["price", "title"], "max_depth": 2},
    )
    assert result.perception_id == "perc-002"
    import json
    sent = json.loads(route.calls[0].request.content)
    assert "constraints" in sent


@respx.mock
def test_synthesize(client: Kloakd) -> None:
    respx.post(f"{TEST_BASE_URL}{ORG_PREFIX}/nexus/synthesize").mock(
        return_value=mock_response({
            "strategy_id": "strat-001",
            "strategy_name": "css_list_extractor",
            "generated_code": "import ...",
            "artifact_id": "art-strat-001",
            "synthesis_time_ms": 450,
            "error": None,
        })
    )
    result = client.nexus.synthesize("perc-001")
    assert isinstance(result, NexusSynthesisResult)
    assert result.strategy_id == "strat-001"
    assert result.strategy_name == "css_list_extractor"
    assert result.ok is True


@respx.mock
def test_verify_safe(client: Kloakd) -> None:
    respx.post(f"{TEST_BASE_URL}{ORG_PREFIX}/nexus/verify").mock(
        return_value=mock_response({
            "verification_result_id": "ver-001",
            "is_safe": True,
            "risk_score": 0.05,
            "safety_score": 0.95,
            "violations": [],
            "duration_ms": 80,
            "error": None,
        })
    )
    result = client.nexus.verify("strat-001")
    assert isinstance(result, NexusVerifyResult)
    assert result.is_safe is True
    assert result.risk_score == 0.05
    assert result.violations == []
    assert result.ok is True


@respx.mock
def test_verify_unsafe(client: Kloakd) -> None:
    respx.post(f"{TEST_BASE_URL}{ORG_PREFIX}/nexus/verify").mock(
        return_value=mock_response({
            "verification_result_id": "ver-002",
            "is_safe": False,
            "risk_score": 0.85,
            "safety_score": 0.15,
            "violations": ["pii_exposure", "excessive_requests"],
            "duration_ms": 80,
            "error": None,
        })
    )
    result = client.nexus.verify("strat-002")
    assert result.is_safe is False
    assert result.ok is False
    assert len(result.violations) == 2


@respx.mock
def test_execute(client: Kloakd) -> None:
    respx.post(f"{TEST_BASE_URL}{ORG_PREFIX}/nexus/execute").mock(
        return_value=mock_response({
            "execution_result_id": "exec-001",
            "success": True,
            "data": [{"title": "Product A", "price": "$10"}],
            "artifact_id": "art-exec-001",
            "duration_ms": 2100,
            "error": None,
        })
    )
    result = client.nexus.execute("strat-001", "https://example.com")
    assert isinstance(result, NexusExecuteResult)
    assert result.success is True
    assert len(result.records) == 1
    assert result.records[0]["title"] == "Product A"
    assert result.ok is True


@respx.mock
def test_knowledge(client: Kloakd) -> None:
    respx.post(f"{TEST_BASE_URL}{ORG_PREFIX}/nexus/knowledge").mock(
        return_value=mock_response({
            "learned_concepts": [{"name": "listing_page", "confidence": 0.9}],
            "learned_patterns": [{"selector": "div.product", "reliability": 0.85}],
            "has_more": False,
            "total": 1,
            "duration_ms": 60,
            "error": None,
        })
    )
    result = client.nexus.knowledge("exec-001")
    assert isinstance(result, NexusKnowledgeResult)
    assert len(result.learned_concepts) == 1
    assert result.learned_concepts[0]["name"] == "listing_page"
    assert result.ok is True


@respx.mock
def test_knowledge_pagination(client: Kloakd) -> None:
    route = respx.post(f"{TEST_BASE_URL}{ORG_PREFIX}/nexus/knowledge")
    route.mock(return_value=mock_response({
        "learned_concepts": [],
        "learned_patterns": [],
        "has_more": False,
        "total": 0,
        "duration_ms": 10,
        "error": None,
    }))
    client.nexus.knowledge("exec-001", limit=50, offset=100)
    import json
    sent = json.loads(route.calls[0].request.content)
    assert sent["limit"] == 50
    assert sent["offset"] == 100


@respx.mock
def test_analyze_error_propagates(client: Kloakd) -> None:
    respx.post(f"{TEST_BASE_URL}{ORG_PREFIX}/nexus/analyze").mock(
        return_value=mock_response({
            "perception_id": "",
            "strategy": {},
            "page_type": "unknown",
            "complexity_level": "unknown",
            "artifact_id": None,
            "duration_ms": 0,
            "error": "LLM timeout",
        })
    )
    result = client.nexus.analyze("https://example.com")
    assert result.ok is False
    assert result.error == "LLM timeout"
