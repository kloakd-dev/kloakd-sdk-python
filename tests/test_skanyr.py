"""Tests for the Skanyr namespace."""

from __future__ import annotations

import pytest
import respx

from kloakd import ApiEndpoint, DiscoverResult, Kloakd
from tests.conftest import TEST_BASE_URL, TEST_ORG_ID, ORG_PREFIX, mock_response


@pytest.fixture
def client() -> Kloakd:
    return Kloakd(api_key="sk-test-key", organization_id=TEST_ORG_ID, base_url=TEST_BASE_URL)


@respx.mock
def test_discover_success(client: Kloakd) -> None:
    respx.post(f"{TEST_BASE_URL}{ORG_PREFIX}/skanyr/discover").mock(
        return_value=mock_response({
            "success": True,
            "discovery_id": "disc-001",
            "url": "https://api.example.com",
            "total_endpoints": 3,
            "endpoints": [
                {"url": "https://api.example.com/products", "method": "GET", "api_type": "rest", "confidence": 0.95, "parameters": {}},
                {"url": "https://api.example.com/products/{id}", "method": "GET", "api_type": "rest", "confidence": 0.90, "parameters": {"id": "string"}},
                {"url": "https://api.example.com/graphql", "method": "POST", "api_type": "graphql", "confidence": 0.88, "parameters": {}},
            ],
            "artifact_id": "art-apimap-001",
            "has_more": False,
            "total": 3,
            "error": None,
        })
    )
    result = client.skanyr.discover("https://api.example.com")
    assert isinstance(result, DiscoverResult)
    assert result.success is True
    assert result.total_endpoints == 3
    assert result.artifact_id == "art-apimap-001"
    assert len(result.endpoints) == 3
    assert isinstance(result.endpoints[0], ApiEndpoint)
    assert result.endpoints[2].api_type == "graphql"
    assert result.ok is True


@respx.mock
def test_discover_with_hierarchy_artifact(client: Kloakd) -> None:
    route = respx.post(f"{TEST_BASE_URL}{ORG_PREFIX}/skanyr/discover")
    route.mock(return_value=mock_response({
        "success": True,
        "discovery_id": "disc-002",
        "url": "https://api.example.com",
        "total_endpoints": 0,
        "endpoints": [],
        "artifact_id": None,
        "has_more": False,
        "total": 0,
        "error": None,
    }))
    client.skanyr.discover(
        "https://api.example.com",
        site_hierarchy_artifact_id="art-hierarchy-001",
        session_artifact_id="art-session-001",
    )
    import json
    sent = json.loads(route.calls[0].request.content)
    assert sent["site_hierarchy_artifact_id"] == "art-hierarchy-001"
    assert sent["session_artifact_id"] == "art-session-001"


@respx.mock
def test_get_api_map(client: Kloakd) -> None:
    respx.get(f"{TEST_BASE_URL}{ORG_PREFIX}/skanyr/api-map/art-apimap-001").mock(
        return_value=mock_response({"artifact_id": "art-apimap-001", "endpoints": []})
    )
    result = client.skanyr.get_api_map("art-apimap-001")
    assert result["artifact_id"] == "art-apimap-001"


@respx.mock
def test_get_job(client: Kloakd) -> None:
    respx.get(f"{TEST_BASE_URL}{ORG_PREFIX}/skanyr/jobs/job-001").mock(
        return_value=mock_response({"job_id": "job-001", "status": "running"})
    )
    result = client.skanyr.get_job("job-001")
    assert result["status"] == "running"


@respx.mock
def test_discover_all_autopaginates(client: Kloakd) -> None:
    call_count = 0

    def paginate(request, **kwargs):
        nonlocal call_count
        call_count += 1
        import json as _j
        offset = _j.loads(request.content).get("offset", 0)
        ep = {"url": f"https://api.example.com/ep{offset}", "method": "GET", "api_type": "rest", "confidence": 0.9, "parameters": {}}
        return mock_response({
            "success": True, "discovery_id": "d1", "url": "https://api.example.com",
            "total_endpoints": 2, "endpoints": [ep],
            "artifact_id": None, "has_more": offset == 0, "total": 2, "error": None,
        })

    respx.post(f"{TEST_BASE_URL}{ORG_PREFIX}/skanyr/discover").mock(side_effect=paginate)
    endpoints = client.skanyr.discover_all("https://api.example.com")
    assert len(endpoints) == 2
    assert call_count == 2


@respx.mock
def test_endpoint_confidence_ordering(client: Kloakd) -> None:
    respx.post(f"{TEST_BASE_URL}{ORG_PREFIX}/skanyr/discover").mock(
        return_value=mock_response({
            "success": True,
            "discovery_id": "disc-003",
            "url": "https://api.example.com",
            "total_endpoints": 2,
            "endpoints": [
                {"url": "https://api.example.com/a", "method": "GET", "api_type": "rest", "confidence": 0.99, "parameters": {}},
                {"url": "https://api.example.com/b", "method": "POST", "api_type": "rest", "confidence": 0.50, "parameters": {}},
            ],
            "artifact_id": None,
            "has_more": False,
            "total": 2,
            "error": None,
        })
    )
    result = client.skanyr.discover("https://api.example.com")
    assert result.endpoints[0].confidence == 0.99
    assert result.endpoints[1].confidence == 0.50
