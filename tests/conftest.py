"""
Shared test fixtures for the KLOAKD Python SDK test suite.

Uses respx to mock httpx at the transport layer — no real network calls.
"""

from __future__ import annotations

import json
from typing import Any, Dict
from unittest.mock import MagicMock

import pytest
import respx
from httpx import Response

from kloakd import Kloakd

TEST_API_KEY = "sk-test-fixture-key"
TEST_ORG_ID = "00000000-0000-0000-0000-000000000001"
TEST_BASE_URL = "https://api.kloakd.dev"
ORG_PREFIX = f"/api/v1/organizations/{TEST_ORG_ID}"


@pytest.fixture
def client() -> Kloakd:
    """A Kloakd client pointed at the mock base URL."""
    return Kloakd(
        api_key=TEST_API_KEY,
        organization_id=TEST_ORG_ID,
        base_url=TEST_BASE_URL,
    )


def mock_response(data: Dict[str, Any], status_code: int = 200) -> Response:
    """Build a mock httpx.Response with JSON body."""
    return Response(status_code, json=data)


def error_response(status_code: int, detail: str = "error") -> Response:
    """Build a mock error httpx.Response."""
    return Response(status_code, json={"detail": detail})
