"""402, 429 and 503 from the billing gate are distinct, typed errors."""

from __future__ import annotations

import pytest
import respx
from httpx import Response

from kloakd import (
    BillingUnavailableError,
    Kloakd,
    PaymentRequiredError,
    QuotaExceededError,
    RateLimitError,
)
from tests.conftest import ORG_PREFIX, TEST_BASE_URL, TEST_ORG_ID

SCAN = f"{TEST_BASE_URL}{ORG_PREFIX}/evadr/scan"


@respx.mock
def test_402_is_payment_required_and_not_retried(client: Kloakd) -> None:
    route = respx.post(SCAN).mock(return_value=Response(402, json={"detail": {"error": "payment_required", "message": "Your last payment did not go through.", "upgrade_url": "/settings/billing"}}))
    with pytest.raises(PaymentRequiredError) as caught:
        client.evadr.scan("https://e.com")
    assert caught.value.message == "Your last payment did not go through."
    assert route.call_count == 1


@respx.mock
def test_429_gb_exhausted_is_quota_exceeded_and_not_retried(client: Kloakd) -> None:
    route = respx.post(SCAN).mock(return_value=Response(429, json={"detail": {"error": "gb_exhausted", "message": "Monthly allocation used", "tier": "pro"}}))
    with pytest.raises(QuotaExceededError) as caught:
        client.evadr.scan("https://e.com")
    assert caught.value.tier == "pro"
    assert route.call_count == 1


@respx.mock
def test_429_rate_limited_reads_retry_after() -> None:
    respx.post(SCAN).mock(return_value=Response(429, headers={"Retry-After": "0"}, json={"detail": {"error": "rate_limited", "retry_after": 7}}))
    client = Kloakd(api_key="k", organization_id=TEST_ORG_ID, base_url=TEST_BASE_URL, max_retries=1)
    with pytest.raises(RateLimitError) as caught:
        client.evadr.scan("https://e.com")
    assert caught.value.retry_after == 0


@respx.mock
def test_503_billing_unavailable_is_retried_after_retry_after(client: Kloakd) -> None:
    route = respx.post(SCAN).mock(return_value=Response(503, headers={"Retry-After": "0"}, json={"detail": {"error": "billing_unavailable", "message": "Usage could not be checked", "reason": "check_failed"}}))
    with pytest.raises(BillingUnavailableError) as caught:
        client.evadr.scan("https://e.com")
    assert caught.value.retry_after == 0
    assert route.call_count == 3  # max_retries attempts
