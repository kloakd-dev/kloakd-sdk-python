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
    """

    def __init__(self, message: str, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code

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


class NotEntitledError(KloakdError):
    """
    Raised when the tenant's plan does not include the requested module (HTTP 403).

    Attributes:
        module: The module name that requires a higher plan (e.g. "fetchyr").
        upgrade_url: Direct URL to upgrade your plan.
    """

    def __init__(
        self,
        message: str,
        module: str = "unknown",
        upgrade_url: str = "",
    ) -> None:
        super().__init__(message, status_code=403)
        self.module = module
        self.upgrade_url = upgrade_url

    def __repr__(self) -> str:
        return (
            f"NotEntitledError(module={self.module!r}, "
            f"upgrade_url={self.upgrade_url!r}, message={self.message!r})"
        )


class RateLimitError(KloakdError):
    """
    Raised when the request rate limit is exceeded (HTTP 429).

    Attributes:
        retry_after: Seconds to wait before retrying. The SDK's built-in
            retry logic honours this automatically on the first 429.
        reset_at: ISO 8601 timestamp when the rate limit window resets.
    """

    def __init__(
        self,
        message: str,
        retry_after: int = 0,
        reset_at: str = "",
    ) -> None:
        super().__init__(message, status_code=429)
        self.retry_after = retry_after
        self.reset_at = reset_at

    def __repr__(self) -> str:
        return (
            f"RateLimitError(retry_after={self.retry_after!r}, "
            f"reset_at={self.reset_at!r}, message={self.message!r})"
        )


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
