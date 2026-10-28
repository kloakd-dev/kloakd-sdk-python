"""Following a request the API hands off as a job (HTTP 202).

The API sits behind Cloudflare, which closes requests at 100 s. A route
that runs the engine answers within about 85 s; if it is still working
then, it answers 202 with ``job_id`` and ``poll_url`` and the work goes on
as a job. These routes do so: ``evadr/fetch`` (``poll_url`` is
``…/evadr/jobs/{job_id}``), ``kolektr/extract``, ``fetchyr/authenticate``,
``fetchyr/form/detect``, ``fetchyr/form/fill``, ``fetchyr/mfa/detect``,
``nexus/analyze``, ``nexus/synthesize`` and ``nexus/execute`` (``poll_url``
is ``/api/v1/organizations/{org}/handoff/{job_id}``, kobe-scraper
``kernel/sync_handoff.py``).

The SDK polls ``poll_url`` until the job's ``status`` is ``completed`` and
returns its ``result``, the body the route would have answered with, so a
caller gets the same typed result either way. ``failed`` raises
JobFailedError; a 404 (the job is unknown or its result expired, which it
does an hour after it ends) raises JobFailedError too; still running when
the wait runs out raises JobTimeoutError. The wait between polls starts at
the poll interval and grows by half each time, up to 15 s.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from kloakd.errors import ApiError, JobFailedError, KloakdError

DEFAULT_POLL_INTERVAL = 3.0
DEFAULT_POLL_TIMEOUT = 15 * 60.0
BACKOFF_FACTOR = 1.5
MAX_POLL_INTERVAL = 15.0


@dataclass(frozen=True)
class PollOptions:
    """How long to wait between polls (seconds, growing) and in all."""

    interval: float = DEFAULT_POLL_INTERVAL
    timeout: float = DEFAULT_POLL_TIMEOUT


def is_handoff(status_code: int, body: Any) -> bool:
    """A 202 whose body names the job and where to poll it."""
    return (
        status_code == 202
        and isinstance(body, dict)
        and isinstance(body.get("job_id"), str)
        and isinstance(body.get("poll_url"), str)
    )


def next_interval(current: float) -> float:
    return min(current * BACKOFF_FACTOR, max(MAX_POLL_INTERVAL, current))


def outcome(state: Any, job_id: str) -> Optional[Dict[str, Any]]:
    """The job's result when completed; raises when failed; None while running."""
    state = state if isinstance(state, dict) else {}
    status = state.get("status")
    if status == "completed":
        result = state.get("result")
        return result if isinstance(result, dict) else {}
    if status == "failed":
        raise JobFailedError(str(state.get("error") or "Job failed"), job_id)
    return None


def expired(exc: KloakdError, job_id: str) -> Optional[JobFailedError]:
    """The JobFailedError for a poll answered 404 (unknown or expired job)."""
    if isinstance(exc, ApiError) and exc.status_code == 404:
        return JobFailedError(
            f"Job {job_id} not found or expired: {exc.message}", job_id
        )
    return None
