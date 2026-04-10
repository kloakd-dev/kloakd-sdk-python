"""Tests for the Fetchyr namespace — including expanded methods."""

from __future__ import annotations

import pytest
import respx

from kloakd import (
    DeduplicationResult,
    FormDetectionResult,
    Kloakd,
    MfaDetectionResult,
    MfaResult,
    SessionResult,
    WorkflowExecutionResult,
    WorkflowResult,
)
from tests.conftest import TEST_BASE_URL, TEST_ORG_ID, ORG_PREFIX, mock_response


@pytest.fixture
def client() -> Kloakd:
    return Kloakd(api_key="sk-test-key", organization_id=TEST_ORG_ID, base_url=TEST_BASE_URL)


@respx.mock
def test_login_success(client: Kloakd) -> None:
    respx.post(f"{TEST_BASE_URL}{ORG_PREFIX}/fetchyr/login").mock(
        return_value=mock_response({
            "success": True,
            "session_id": "sess-001",
            "url": "https://app.example.com/dashboard",
            "artifact_id": "art-session-001",
            "screenshot_url": None,
            "error": None,
        })
    )
    result = client.fetchyr.login(
        url="https://app.example.com/login",
        username_selector="#email",
        password_selector="#password",
        username="user@example.com",
        password="s3cr3t",
    )
    assert isinstance(result, SessionResult)
    assert result.success is True
    assert result.artifact_id == "art-session-001"
    assert result.ok is True


@respx.mock
def test_create_workflow(client: Kloakd) -> None:
    respx.post(f"{TEST_BASE_URL}{ORG_PREFIX}/fetchyr/workflows").mock(
        return_value=mock_response({
            "workflow_id": "wf-001",
            "name": "Login and scrape",
            "steps": [{"action": "click", "selector": "#login"}],
            "url": "https://app.example.com",
            "created_at": "2026-04-09T00:00:00Z",
            "error": None,
        })
    )
    result = client.fetchyr.create_workflow(
        name="Login and scrape",
        steps=[{"action": "click", "selector": "#login"}],
        url="https://app.example.com",
    )
    assert isinstance(result, WorkflowResult)
    assert result.workflow_id == "wf-001"
    assert result.ok is True


@respx.mock
def test_execute_workflow(client: Kloakd) -> None:
    respx.post(f"{TEST_BASE_URL}{ORG_PREFIX}/fetchyr/workflows/wf-001/execute").mock(
        return_value=mock_response({
            "execution_id": "exec-001",
            "workflow_id": "wf-001",
            "status": "completed",
            "started_at": "2026-04-09T00:00:00Z",
            "completed_at": "2026-04-09T00:00:10Z",
            "records": [{"data": "value"}],
            "error": None,
        })
    )
    result = client.fetchyr.execute_workflow("wf-001")
    assert isinstance(result, WorkflowExecutionResult)
    assert result.status == "completed"
    assert result.ok is True


@respx.mock
def test_get_execution(client: Kloakd) -> None:
    respx.get(f"{TEST_BASE_URL}{ORG_PREFIX}/fetchyr/workflows/wf-001/executions/exec-001").mock(
        return_value=mock_response({
            "execution_id": "exec-001",
            "workflow_id": "wf-001",
            "status": "running",
            "started_at": "2026-04-09T00:00:00Z",
            "completed_at": None,
            "records": [],
            "error": None,
        })
    )
    result = client.fetchyr.get_execution("wf-001", "exec-001")
    assert result.status == "running"
    assert result.ok is False


@respx.mock
def test_detect_forms(client: Kloakd) -> None:
    respx.post(f"{TEST_BASE_URL}{ORG_PREFIX}/fetchyr/detect-forms").mock(
        return_value=mock_response({
            "forms": [
                {"selector": "form#login", "fields": ["#email", "#password"], "action": "/login", "method": "POST", "confidence": 0.98}
            ],
            "total_forms": 1,
            "error": None,
        })
    )
    result = client.fetchyr.detect_forms("https://example.com/login")
    assert isinstance(result, FormDetectionResult)
    assert result.total_forms == 1
    assert result.forms[0]["confidence"] == 0.98


@respx.mock
def test_detect_mfa(client: Kloakd) -> None:
    respx.post(f"{TEST_BASE_URL}{ORG_PREFIX}/fetchyr/detect-mfa").mock(
        return_value=mock_response({
            "mfa_detected": True,
            "challenge_id": "challenge-001",
            "mfa_type": "totp",
            "error": None,
        })
    )
    result = client.fetchyr.detect_mfa("https://app.example.com/mfa")
    assert isinstance(result, MfaDetectionResult)
    assert result.mfa_detected is True
    assert result.mfa_type == "totp"
    assert result.challenge_id == "challenge-001"


@respx.mock
def test_submit_mfa(client: Kloakd) -> None:
    respx.post(f"{TEST_BASE_URL}{ORG_PREFIX}/fetchyr/submit-mfa").mock(
        return_value=mock_response({
            "success": True,
            "session_artifact_id": "art-session-002",
            "error": None,
        })
    )
    result = client.fetchyr.submit_mfa("challenge-001", "123456")
    assert isinstance(result, MfaResult)
    assert result.success is True
    assert result.session_artifact_id == "art-session-002"


@respx.mock
def test_check_duplicates(client: Kloakd) -> None:
    records = [
        {"title": "Book A", "price": "$10"},
        {"title": "Book A", "price": "$10"},
        {"title": "Book B", "price": "$15"},
    ]
    respx.post(f"{TEST_BASE_URL}{ORG_PREFIX}/fetchyr/deduplicate").mock(
        return_value=mock_response({
            "unique_records": [
                {"title": "Book A", "price": "$10"},
                {"title": "Book B", "price": "$15"},
            ],
            "duplicate_count": 1,
            "total_input": 3,
            "error": None,
        })
    )
    result = client.fetchyr.check_duplicates(records, domain="example.com")
    assert isinstance(result, DeduplicationResult)
    assert len(result.unique_records) == 2
    assert result.duplicate_count == 1
    assert result.total_input == 3
    assert result.ok is True
