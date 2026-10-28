"""
KLOAKD SDK — Error hierarchy.

All SDK errors descend from KloakdError. Catch the base class for broad
handling, or catch specific subclasses for targeted recovery.

Example::

    from kloakd.errors import KloakdError, RateLimitError, AuthenticationError

    try:
        result = client.evadr.fetch("https://example.com")
    except RateLimitError as e:
        time.sleep(e.retry_after)
    except AuthenticationError:
        # rotate API key
        raise
    except KloakdError as e:
        logger.error("KLOAKD API error %d: %s", e.status_code, e.message)
"""

from __future__ import annotations

from typing import Optional


class KloakdError(Exception):
    """
    Base class for all KLOAKD SDK errors.

    Attributes:
        message: Human-readable error description.
        status_code: HTTP status code from the API, or None for client-side errors.
        code: The API's error code (``detail.error``, e.g. ``rate_limited``,
            ``not_entitled``), or None when it sent none.
    """

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        code: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(status_code={self.status_code!r}, message={self.message!r})"


class AuthenticationError(KloakdError):
    """
    Raised when the API key is invalid or expired (HTTP 401).

    Resolution: generate a new API key from the KLOAKD dashboard
    at https://app.kloakd.dev/settings/api-keys.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=401)


class ForbiddenError(KloakdError):
    """
    Raised for HTTP 403. This class itself is a 403 that is not a plan
    restriction: the key or user may not access this resource (for example
    another organisation's). Plan restrictions raise its subclass
    NotEntitledError.
    """

    def __init__(self, message: str, code: Optional[str] = None) -> None:
        super().__init__(message, status_code=403, code=code)


class NotEntitledError(ForbiddenError):
    """
    Raised when the plan does not include the requested module or feature
    (HTTP 403 ``not_entitled`` or ``tier_access_denied``).

    Attributes:
        module: The module that requires a higher plan (e.g. "fetchyr"); for
            ``tier_access_denied`` the feature the tier lacks.
        upgrade_url: Direct URL to upgrade your plan.
        code: ``not_entitled`` or ``tier_access_denied``.
        feature: The feature the tier lacks (``tier_access_denied`` only).
        current_tier: The organisation's tier (``tier_access_denied`` only).
        required_tier: The tier the feature needs (``tier_access_denied`` only).
    """

    def __init__(
        self,
        message: str,
        module: str = "unknown",
        upgrade_url: str = "",
        code: str = "not_entitled",
        feature: Optional[str] = None,
        current_tier: Optional[str] = None,
        required_tier: Optional[str] = None,
    ) -> None:
        super().__init__(message, code=code)
        self.module = module
        self.upgrade_url = upgrade_url
        self.feature = feature
        self.current_tier = current_tier
        self.required_tier = required_tier

    def __repr__(self) -> str:
        return (
            f"NotEntitledError(module={self.module!r}, "
            f"upgrade_url={self.upgrade_url!r}, message={self.message!r})"
        )


class RateLimitError(KloakdError):
    """
    Raised when the request rate limit is exceeded (HTTP 429 ``rate_limited``).

    Attributes:
        retry_after: Seconds to wait before retrying. The SDK's built-in
            retry logic honours this (or ``reset_at``) automatically.
        reset_at: ISO 8601 timestamp when the rate limit window resets.
        quota_exhausted: True for the playground (test-key) quota, which
            does not reset: the API sends ``retry_after`` 0 and no
            ``reset_at`` (kobe-scraper kernel/gateway/rate_limiter.py), and
            the SDK does not retry.
        quota_used, quota_limit: The playground quota's use and size.
        upgrade_url: Where to upgrade (playground quota only).
    """

    def __init__(
        self,
        message: str,
        retry_after: int = 0,
        reset_at: str = "",
        quota_used: Optional[int] = None,
        quota_limit: Optional[int] = None,
        upgrade_url: Optional[str] = None,
    ) -> None:
        super().__init__(message, status_code=429, code="rate_limited")
        self.retry_after = retry_after
        self.reset_at = reset_at
        self.quota_used = quota_used
        self.quota_limit = quota_limit
        self.upgrade_url = upgrade_url

    @property
    def quota_exhausted(self) -> bool:
        """True for the playground quota: no wait will lift it (not retried)."""
        return self.retry_after <= 0 and not self.reset_at

    def __repr__(self) -> str:
        return (
            f"RateLimitError(retry_after={self.retry_after!r}, "
            f"reset_at={self.reset_at!r}, message={self.message!r})"
        )


class ConcurrencyLimitError(KloakdError):
    """
    Raised when the organisation already runs as many crawls or jobs as its
    tier allows (HTTP 409 ``concurrent_limit``). Retry once one finishes.

    Attributes:
        concurrent_limit: The number allowed at once.
        active_crawls: How many are running (tier limit only).
        tier: The organisation's tier (tier limit only).
    """

    def __init__(
        self,
        message: str,
        concurrent_limit: Optional[int] = None,
        active_crawls: Optional[int] = None,
        tier: Optional[str] = None,
    ) -> None:
        super().__init__(message, status_code=409)
        self.concurrent_limit = concurrent_limit
        self.active_crawls = active_crawls
        self.tier = tier


class UpstreamError(KloakdError):
    """
    Raised when the upstream site fetch fails (HTTP 502).

    This indicates the target website, not the KLOAKD API, is unreachable
    or returned an unexpected response. Retry with a different tier or proxy.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=502)


class ApiError(KloakdError):
    """
    Raised for any other 4xx or 5xx response not covered by a specific subclass.

    Attributes:
        status_code: The HTTP status code returned.
        message: Error detail from the API response body.
    """

    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message, status_code=status_code)


class PaymentRequiredError(KloakdError):
    """
    Raised when a paid plan's last payment failed (HTTP 402
    ``payment_required``). New work starts again once the payment is settled.
    """

    def __init__(self, message: str, upgrade_url: str = "https://app.kloakd.dev/settings/billing") -> None:
        super().__init__(message, status_code=402)
        self.upgrade_url = upgrade_url


class QuotaExceededError(KloakdError):
    """
    Raised when the plan's GB allocation and this period's top-ups are used
    up (HTTP 429 ``gb_exhausted``). Not retried: retrying cannot succeed.
    """

    def __init__(self, message: str, tier: str = "", upgrade_url: str = "https://app.kloakd.dev/settings/billing") -> None:
        super().__init__(message, status_code=429)
        self.tier = tier
        self.upgrade_url = upgrade_url


class BillingUnavailableError(KloakdError):
    """
    Raised when the API could not check usage, so nothing was started
    (HTTP 503 ``billing_unavailable``). Retried after ``retry_after`` seconds.
    """

    def __init__(self, message: str, retry_after: float = 30.0) -> None:
        super().__init__(message, status_code=503)
        self.retry_after = retry_after


class JobFailedError(KloakdError):
    """Raised when a job (a handed-off fetch, an async fetch or a crawl) ended as failed."""

    def __init__(self, message: str, job_id: str) -> None:
        super().__init__(message, status_code=None)
        self.job_id = job_id


class JobTimeoutError(KloakdError):
    """Raised when a job was still running when the SDK's wait ran out.

    Resume with ``client.wait_for_handoff(e.job_id)`` (a handed-off request),
    ``client.evadr.wait_for_job(e.job_id)`` (a fetch job) or
    ``client.webgrph.get_crawl_status(e.job_id)`` (a crawl)."""

    def __init__(self, message: str, job_id: str) -> None:
        super().__init__(message, status_code=None)
        self.job_id = job_id
