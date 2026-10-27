"""Fetchyr: authenticated sessions, forms, MFA, workflows, deduplication."""

from __future__ import annotations

import json

import respx

from kloakd import DuplicateCheckResult, Kloakd, MfaChallenge, SessionResult
from tests.conftest import ORG_PREFIX, TEST_BASE_URL, mock_response

BASE = f"{TEST_BASE_URL}{ORG_PREFIX}"


def _sent(route: respx.Route) -> dict:
    return json.loads(route.calls.last.request.content)


@respx.mock
def test_authenticate_uses_stored_credentials(client: Kloakd) -> None:
    route = respx.post(f"{BASE}/fetchyr/authenticate").mock(return_value=mock_response(
        {"success": True, "session_id": "sess-1", "artifact_id": "art-1", "target_domain": "example.com", "auth_method": "form"}
    ))
    result = client.fetchyr.authenticate("my-login", "https://example.com/login")
    assert isinstance(result, SessionResult)
    assert _sent(route) == {"credential_name": "my-login", "target_url": "https://example.com/login"}
    assert (result.ok, result.artifact_id, result.auth_method) == (True, "art-1", "form")


@respx.mock
def test_store_credentials_sends_the_api_fields(client: Kloakd) -> None:
    route = respx.post(f"{BASE}/fetchyr/account/credentials").mock(return_value=mock_response({"name": "my-login"}))
    client.fetchyr.store_credentials("my-login", username="u", password="p")
    assert _sent(route) == {"name": "my-login", "username": "u", "password": "p"}


@respx.mock
def test_create_and_execute_workflow(client: Kloakd) -> None:
    create = respx.post(f"{BASE}/fetchyr/workflows").mock(return_value=mock_response(
        {"id": "wf-1", "name": "w", "steps": [{"a": 1}], "is_active": True, "created_at": "t"}
    ))
    wf = client.fetchyr.create_workflow("w", [{"a": 1}], description="d")
    assert _sent(create) == {"name": "w", "steps": [{"a": 1}], "description": "d"}
    assert wf.workflow_id == "wf-1"

    run = respx.post(f"{BASE}/fetchyr/workflows/wf-1/execute").mock(return_value=mock_response(
        {"execution_id": "ex-1", "workflow_id": "wf-1", "status": "completed", "result": {"n": 1}}
    ))
    ex = client.fetchyr.execute_workflow("wf-1", "https://example.com", session_artifact_id="s")
    assert _sent(run) == {"target_url": "https://example.com", "session_artifact_id": "s"}
    assert (ex.ok, ex.result) == (True, {"n": 1})


@respx.mock
def test_detect_forms_at_form_detect(client: Kloakd) -> None:
    respx.post(f"{BASE}/fetchyr/form/detect").mock(return_value=mock_response(
        {"url": "u", "forms_found": 1, "login_form_detected": True, "fields": [{"name": "email"}]}
    ))
    r = client.fetchyr.detect_forms("u")
    assert (r.total_forms, r.login_form_detected, len(r.forms)) == (1, True, 1)


@respx.mock
def test_detect_mfa_and_resolve_the_challenge(client: Kloakd) -> None:
    respx.post(f"{BASE}/fetchyr/mfa/detect").mock(return_value=mock_response(
        {"mfa_detected": True, "mfa_type": "totp", "challenge_id": "ch-1", "message": "enter code"}
    ))
    d = client.fetchyr.detect_mfa("u")
    assert (d.mfa_detected, d.challenge_id, d.message) == (True, "ch-1", "enter code")

    resolve = respx.post(f"{BASE}/fetchyr/mfa-queue/ch-1/resolve").mock(return_value=mock_response(
        {"id": "ch-1", "status": "resolved", "mfa_type": "totp"}
    ))
    c = client.fetchyr.submit_mfa("ch-1", "123456")
    assert isinstance(c, MfaChallenge)
    assert _sent(resolve) == {"resolution": "123456"}
    assert c.status == "resolved"


@respx.mock
def test_check_one_url_for_duplicates(client: Kloakd) -> None:
    route = respx.post(f"{BASE}/fetchyr/deduplication/check").mock(return_value=mock_response(
        {"is_duplicate": True, "original_url": "https://e.com/a", "similarity_score": 1.0, "match_type": "exact"}
    ))
    r = client.fetchyr.check_duplicate("https://e.com/a?x", session_id="ds-1")
    assert isinstance(r, DuplicateCheckResult)
    assert _sent(route) == {"url": "https://e.com/a?x", "session_id": "ds-1"}
    assert (r.is_duplicate, r.match_type) == (True, "exact")
