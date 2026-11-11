"""Nexus: analyse, synthesise, verify, reason."""

from __future__ import annotations

import json

import pytest
import respx
from httpx import Response

from kloakd import ApiError, Kloakd
from tests.conftest import ORG_PREFIX, TEST_BASE_URL, mock_response

BASE = f"{TEST_BASE_URL}{ORG_PREFIX}"


def _sent(route: respx.Route) -> dict:
    return json.loads(route.calls.last.request.content)


@respx.mock
def test_analyze_sends_url_and_html(client: Kloakd) -> None:
    route = respx.post(f"{BASE}/nexus/analyze").mock(return_value=mock_response(
        {"url": "https://e.com", "page_type": "listing", "confidence": 0.9, "strategy": {"s": 1}, "perception_id": "p1", "artifact": {"artifact_id": "a1"}}
    ))
    r = client.nexus.analyze("https://e.com", "<html></html>", constraints={"max_fields": 3})
    assert _sent(route) == {"url": "https://e.com", "html": "<html></html>", "constraints": {"max_fields": 3}}
    assert (r.page_type, r.confidence, r.perception_id, r.artifact_id, r.ok) == ("listing", 0.9, "p1", "a1", True)


@respx.mock
def test_synthesize_sends_url_html_and_goal(client: Kloakd) -> None:
    route = respx.post(f"{BASE}/nexus/synthesize").mock(return_value=mock_response(
        {"url": "u", "goal": "g", "program": "code", "strategy_id": "s1", "strategy_name": "n", "synthesis_time_ms": 12}
    ))
    r = client.nexus.synthesize("u", "<html/>", "g")
    assert _sent(route) == {"url": "u", "html": "<html/>", "goal": "g"}
    assert (r.program, r.strategy_id, r.synthesis_time_ms) == ("code", "s1", 12)


@respx.mock
def test_verify_reads_verified(client: Kloakd) -> None:
    respx.post(f"{BASE}/nexus/verify").mock(return_value=mock_response({"strategy_id": "s1", "verified": False, "violations": ["net"], "safety_score": 0.2}))
    r = client.nexus.verify("s1")
    assert (r.verified, r.violations, r.ok) == (False, ["net"], False)


@respx.mock
def test_verify_reads_the_whole_response(client: Kloakd) -> None:
    # modules/nexus/router.py VerifyResponse
    respx.post(f"{BASE}/nexus/verify").mock(return_value=mock_response({
        "strategy_id": "s1", "verified": True, "violations": [], "safety_score": 0.9,
        "verification_result_id": "v-1", "status": "verified", "risk_score": 0.1,
        "duration_ms": 42,
        "safety_checks": [
            {"property": "no_network", "passed": True, "details": "ok"},
            {"property": "bounded", "passed": False},
        ],
    }))
    r = client.nexus.verify("s1")
    assert (r.status, r.risk_score, r.verification_result_id, r.duration_ms) == ("verified", 0.1, "v-1", 42)
    assert [(c.property, c.passed, c.details) for c in r.safety_checks] == [
        ("no_network", True, "ok"), ("bounded", False, ""),
    ]
    assert r.ok


def test_execute_and_knowledge_are_removed(client: Kloakd) -> None:
    import kloakd

    assert not hasattr(client.nexus, "execute")
    assert not hasattr(client.nexus, "knowledge")
    assert not hasattr(kloakd, "NexusExecuteResult")
    assert not hasattr(kloakd, "NexusKnowledgeResult")


@respx.mock
def test_reason_sends_query_type(client: Kloakd) -> None:
    route = respx.post(f"{BASE}/nexus/reason").mock(return_value=mock_response({}))
    client.nexus.reason("page_type", ["https://e.com"])
    # modules/nexus/router.py ReasonRequest: parameters is List[str]
    assert _sent(route) == {"query_type": "page_type", "parameters": ["https://e.com"]}


@respx.mock
def test_reason_sends_an_empty_parameter_list_by_default(client: Kloakd) -> None:
    route = respx.post(f"{BASE}/nexus/reason").mock(return_value=mock_response({}))
    client.nexus.reason("page_type")
    assert _sent(route)["parameters"] == []


@respx.mock
def test_an_api_error_is_raised(client: Kloakd) -> None:
    respx.post(f"{BASE}/nexus/analyze").mock(return_value=Response(422, json={"detail": "html is required"}))
    with pytest.raises(ApiError):
        client.nexus.analyze("https://e.com", "")
