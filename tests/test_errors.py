"""Tests for the KloakdError hierarchy and error mapping."""

from __future__ import annotations

import pytest
import respx
from httpx import Response

from kloakd import (
    ApiError,
    AuthenticationError,
    Kloakd,
    KloakdError,
    NotEntitledError,
    RateLimitError,
    UpstreamError,
)
from kloakd._http import _HttpTransport
from tests.conftest import TEST_BASE_URL, TEST_ORG_ID, ORG_PREFIX


@pytest.fixture
def client() -> Kloakd:
    return Kloakd(api_key="sk-test-key", organization_id=TEST_ORG_ID, base_url=TEST_BASE_URL)


class TestErrorHierarchy:
    def test_authentication_error_is_kloakd_error(self) -> None:
        err = AuthenticationError("bad key")
        assert isinstance(err, KloakdError)
        assert err.status_code == 401

    def test_not_entitled_error_fields(self) -> None:
        err = NotEntitledError("no access", module="nexus", upgrade_url="https://kloakd.dev/billing")
        assert isinstance(err, KloakdError)
        assert err.status_code == 403
        assert err.module == "nexus"
        assert "billing" in err.upgrade_url

    def test_rate_limit_error_fields(self) -> None:
        err = RateLimitError("slow down", retry_after=45, reset_at="2026-01-01T00:00:00Z")
        assert isinstance(err, KloakdError)
        assert err.status_code == 429
        assert err.retry_after == 45
        assert err.reset_at == "2026-01-01T00:00:00Z"

    def test_upstream_error(self) -> None:
        err = UpstreamError("site unreachable")
        assert isinstance(err, KloakdError)
        assert err.status_code == 502

    def test_api_error(self) -> None:
        err = ApiError("not found", status_code=404)
        assert isinstance(err, KloakdError)
        assert err.status_code == 404

    def test_repr_includes_status_code(self) -> None:
        err = RateLimitError("slow", retry_after=10)
        assert "10" in repr(err)
        assert "slow" in repr(err)


class TestErrorMapping:
    def test_raise_for_status_401(self) -> None:
        with pytest.raises(AuthenticationError):
            _HttpTransport._raise_for_status(401, b'{"detail": "bad key"}')

    def test_raise_for_status_403(self) -> None:
        import json
        body = json.dumps({"detail": "forbidden", "module": "fetchyr"}).encode()
        with pytest.raises(NotEntitledError) as exc_info:
            _HttpTransport._raise_for_status(403, body)
        assert exc_info.value.module == "fetchyr"

    def test_raise_for_status_429(self) -> None:
        import json
        body = json.dumps({"detail": "rate limited", "retry_after": 60}).encode()
        with pytest.raises(RateLimitError) as exc_info:
            _HttpTransport._raise_for_status(429, body)
        assert exc_info.value.retry_after == 60

    def test_raise_for_status_502(self) -> None:
        with pytest.raises(UpstreamError):
            _HttpTransport._raise_for_status(502, b'{"detail": "upstream down"}')

    def test_raise_for_status_404(self) -> None:
        with pytest.raises(ApiError) as exc_info:
            _HttpTransport._raise_for_status(404, b'{"detail": "not found"}')
        assert exc_info.value.status_code == 404

    def test_raise_for_status_200_no_raise(self) -> None:
        _HttpTransport._raise_for_status(200, b"{}")

    def test_raise_for_status_201_no_raise(self) -> None:
        _HttpTransport._raise_for_status(201, b"{}")


class TestClientValidation:
    def test_empty_api_key_raises(self) -> None:
        with pytest.raises(ValueError, match="api_key"):
            Kloakd(api_key="", organization_id=TEST_ORG_ID)

    def test_empty_org_id_raises(self) -> None:
        with pytest.raises(ValueError, match="organization_id"):
            Kloakd(api_key="sk-test-key", organization_id="")

    def test_whitespace_api_key_raises(self) -> None:
        with pytest.raises(ValueError, match="api_key"):
            Kloakd(api_key="   ", organization_id=TEST_ORG_ID)
