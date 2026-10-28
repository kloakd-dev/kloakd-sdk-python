"""A synchronous route answers within ~85 s; past that the API returns 202
and the work continues as a job (Cloudflare closes requests at 100 s).

evadr/fetch polls its own job route (``…/evadr/jobs/{id}``); kolektr extract,
the four fetchyr routes and nexus analyze/synthesize/execute poll
``/api/v1/organizations/{org}/handoff/{id}`` (kobe-scraper
``kernel/sync_handoff.py``). The SDK follows ``poll_url`` either way.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Tuple

import pytest
import respx
from httpx import Response

import kloakd._http as http_mod
from kloakd import AsyncKloakd, JobFailedError, JobTimeoutError, Kloakd, KloakdError
from tests.conftest import ORG_PREFIX, TEST_API_KEY, TEST_BASE_URL, TEST_ORG_ID, mock_response

BASE = f"{TEST_BASE_URL}{ORG_PREFIX}"
PAGE = {"success": True, "url": "https://www.economist.com/", "status_code": 200, "tier_used": 3, "html": "<html></html>", "error": None}
HANDED_OFF = {"job_id": "job-1", "status": "running", "reason": "sync_limit_reached", "waited_seconds": 85, "poll_url": f"{ORG_PREFIX}/evadr/jobs/job-1", "message": ""}
EVADR_JOB = f"{BASE}/evadr/jobs/job-1"
HANDOFF_JOB = f"{BASE}/handoff/h-1"


def handed_off(job_id: str = "h-1") -> Dict[str, Any]:
    """The 202 body of a route decorated with @hands_off_after_limit."""
    return {
        "job_id": job_id, "status": "running", "reason": "sync_limit_reached",
        "waited_seconds": 85.0, "poll_url": f"{ORG_PREFIX}/handoff/{job_id}",
        "message": "Still running; it continues as a job. Poll poll_url for the result.",
    }


def running(job_id: str = "h-1") -> Response:
    return mock_response({"job_id": job_id, "kind": "x", "status": "running", "started_at": 1.0})


def completed(result: Dict[str, Any], job_id: str = "h-1") -> Response:
    return mock_response({"job_id": job_id, "kind": "x", "status": "completed", "result": result, "completed_at": 2.0})


# (route, call, the route's 200 body, check on the typed result)
Case = Tuple[str, Callable[[Any], Any], Dict[str, Any], Callable[[Any], bool]]
CASES: List[Case] = [
    ("kolektr/extract", lambda c: c.kolektr.page("https://x.example"),
     {"success": True, "url": "https://x.example", "records": [{"a": 1}], "total_records": 1},
     lambda r: r.records == [{"a": 1}] and r.total_records == 1),
    ("fetchyr/authenticate", lambda c: c.fetchyr.authenticate("acme", "https://x.example/login"),
     {"success": True, "session_id": "s-1", "artifact_id": "art-1"},
     lambda r: (r.session_id, r.artifact_id) == ("s-1", "art-1")),
    ("fetchyr/form/detect", lambda c: c.fetchyr.detect_forms("https://x.example"),
     {"url": "https://x.example", "forms_found": 2, "fields": [{"name": "q"}]},
     lambda r: (r.total_forms, r.forms) == (2, [{"name": "q"}])),
    ("fetchyr/form/fill", lambda c: c.fetchyr.fill_form("https://x.example", {"q": "v"}),
     {"success": True, "submitted": True},
     lambda r: r == {"success": True, "submitted": True}),
    ("fetchyr/mfa/detect", lambda c: c.fetchyr.detect_mfa("https://x.example"),
     {"mfa_detected": True, "challenge_id": "ch-1", "mfa_type": "totp"},
     lambda r: (r.mfa_detected, r.challenge_id) == (True, "ch-1")),
    ("nexus/analyze", lambda c: c.nexus.analyze("https://x.example", "<html/>"),
     {"url": "https://x.example", "perception_id": "p-1", "page_type": "listing", "confidence": 0.9},
     lambda r: (r.perception_id, r.page_type) == ("p-1", "listing")),
    ("nexus/synthesize", lambda c: c.nexus.synthesize("https://x.example", "<html/>", "prices"),
     {"url": "https://x.example", "goal": "prices", "strategy_id": "st-1", "program": "p"},
     lambda r: (r.strategy_id, r.program) == ("st-1", "p")),
    ("nexus/execute", lambda c: c.nexus.execute("st-1", "https://x.example"),
     {"url": "https://x.example", "strategy_id": "st-1", "success": True, "records": [{"b": 2}], "duration_ms": 5, "execution_result_id": "er-1"},
     lambda r: (r.records, r.execution_result_id) == ([{"b": 2}], "er-1")),
]
IDS = [c[0] for c in CASES]


@pytest.fixture
def fast_client() -> Kloakd:
    return Kloakd(api_key=TEST_API_KEY, organization_id=TEST_ORG_ID, base_url=TEST_BASE_URL, poll_interval=0.001)


@pytest.fixture
def fast_async_client() -> AsyncKloakd:
    return AsyncKloakd(api_key=TEST_API_KEY, organization_id=TEST_ORG_ID, base_url=TEST_BASE_URL, poll_interval=0.001)


# ── Every hand-off route ───────────────────────────────────────────────


@pytest.mark.parametrize(("route", "call", "body", "check"), CASES, ids=IDS)
@respx.mock
def test_each_route_follows_a_202_to_its_typed_result(fast_client: Kloakd, route: str, call: Any, body: Dict[str, Any], check: Any) -> None:
    post = respx.post(f"{BASE}/{route}").mock(return_value=mock_response(handed_off(), 202))
    poll = respx.get(HANDOFF_JOB).mock(side_effect=[running(), running(), completed(body)])
    assert check(call(fast_client))
    assert post.call_count == 1 and poll.call_count == 3
    request = poll.calls.last.request
    assert request.headers["Authorization"] == f"Bearer {TEST_API_KEY}"
    assert request.headers["X-Kloakd-Organization"] == TEST_ORG_ID


@pytest.mark.parametrize(("route", "call", "body", "check"), CASES, ids=IDS)
@respx.mock
def test_each_route_answered_in_time_is_not_polled(fast_client: Kloakd, route: str, call: Any, body: Dict[str, Any], check: Any) -> None:
    respx.post(f"{BASE}/{route}").mock(return_value=mock_response(body))
    poll = respx.get(HANDOFF_JOB)
    assert check(call(fast_client))
    assert not poll.called


@pytest.mark.parametrize(("route", "call", "body", "check"), CASES, ids=IDS)
@respx.mock
async def test_the_async_client_follows_each_route(fast_async_client: AsyncKloakd, route: str, call: Any, body: Dict[str, Any], check: Any) -> None:
    respx.post(f"{BASE}/{route}").mock(return_value=mock_response(handed_off(), 202))
    respx.get(HANDOFF_JOB).mock(side_effect=[running(), completed(body)])
    assert check(await call(fast_async_client))


# ── The follower ───────────────────────────────────────────────────────


@respx.mock
def test_a_200_that_carries_a_job_id_is_the_answer(fast_client: Kloakd) -> None:
    body = {"success": True, "url": "https://x.example", "records": [], "job_id": "kj-1", "poll_url": "/anything"}
    respx.post(f"{BASE}/kolektr/extract").mock(return_value=mock_response(body))
    poll = respx.get(url__regex=r".*")
    assert fast_client.kolektr.page("https://x.example").job_id == "kj-1"
    assert not poll.called


@respx.mock
def test_a_failed_hand_off_raises_with_the_route_error(fast_client: Kloakd) -> None:
    respx.post(f"{BASE}/nexus/execute").mock(return_value=mock_response(handed_off(), 202))
    respx.get(HANDOFF_JOB).mock(return_value=mock_response({"job_id": "h-1", "status": "failed", "error": "Strategy Engine execution failed: boom"}))
    with pytest.raises(JobFailedError) as caught:
        fast_client.nexus.execute("st-1", "https://x.example")
    assert (caught.value.job_id, caught.value.message) == ("h-1", "Strategy Engine execution failed: boom")


@respx.mock
def test_an_expired_hand_off_raises_job_failed(fast_client: Kloakd) -> None:
    respx.post(f"{BASE}/kolektr/extract").mock(return_value=mock_response(handed_off(), 202))
    respx.get(HANDOFF_JOB).mock(return_value=Response(404, json={"detail": "Job h-1 not found or expired"}))
    with pytest.raises(JobFailedError) as caught:
        fast_client.kolektr.page("https://x.example")
    assert caught.value.job_id == "h-1"
    assert "not found or expired" in caught.value.message


@respx.mock
def test_other_poll_errors_are_raised_as_they_are(fast_client: Kloakd) -> None:
    from kloakd import AuthenticationError

    respx.post(f"{BASE}/kolektr/extract").mock(return_value=mock_response(handed_off(), 202))
    respx.get(HANDOFF_JOB).mock(return_value=Response(401, json={"detail": "bad key"}))
    with pytest.raises(AuthenticationError):
        fast_client.kolektr.page("https://x.example")


@respx.mock
def test_a_hand_off_still_running_at_the_timeout_raises(client: Kloakd) -> None:
    slow = Kloakd(api_key="k", organization_id=TEST_ORG_ID, base_url=TEST_BASE_URL, poll_interval=0.005, poll_timeout=0.008)
    respx.post(f"{BASE}/fetchyr/form/detect").mock(return_value=mock_response(handed_off(), 202))
    respx.get(HANDOFF_JOB).mock(return_value=running())
    with pytest.raises(JobTimeoutError) as caught:
        slow.fetchyr.detect_forms("https://x.example")
    assert caught.value.job_id == "h-1"


@respx.mock
def test_polls_back_off_by_half_up_to_15_seconds(monkeypatch: pytest.MonkeyPatch, client: Kloakd) -> None:
    waits: List[float] = []
    monkeypatch.setattr(http_mod.time, "sleep", waits.append)
    respx.post(f"{BASE}/nexus/analyze").mock(return_value=mock_response(handed_off(), 202))
    respx.get(HANDOFF_JOB).mock(side_effect=[running()] * 6 + [completed({"perception_id": "p"})])
    assert client.nexus.analyze("https://x.example", "<html/>").perception_id == "p"
    assert waits == [3.0, 4.5, 6.75, 10.125, 15.0, 15.0, 15.0]


@respx.mock
def test_a_poll_url_on_another_host_is_refused(fast_client: Kloakd) -> None:
    body = {**handed_off(), "poll_url": "https://elsewhere.example/api/v1/x"}
    respx.post(f"{BASE}/kolektr/extract").mock(return_value=mock_response(body, 202))
    with pytest.raises(KloakdError, match="Refusing to poll"):
        fast_client.kolektr.page("https://x.example")


@respx.mock
def test_a_full_poll_url_on_the_base_url_is_followed(fast_client: Kloakd) -> None:
    body = {**handed_off(), "poll_url": HANDOFF_JOB}
    respx.post(f"{BASE}/kolektr/extract").mock(return_value=mock_response(body, 202))
    respx.get(HANDOFF_JOB).mock(return_value=completed({"records": [1]}))
    assert fast_client.kolektr.page("https://x.example").records == [1]


@respx.mock
def test_a_completed_job_without_a_result_parses_as_empty(fast_client: Kloakd) -> None:
    respx.post(f"{BASE}/fetchyr/form/fill").mock(return_value=mock_response(handed_off(), 202))
    respx.get(HANDOFF_JOB).mock(return_value=mock_response({"job_id": "h-1", "status": "completed"}))
    assert fast_client.fetchyr.fill_form("https://x.example", {"q": "v"}) == {}


# ── evadr/fetch (its own poll_url) ─────────────────────────────────────


@respx.mock
def test_answered_in_time_is_the_page(client: Kloakd) -> None:
    respx.post(f"{BASE}/evadr/fetch").mock(return_value=mock_response(PAGE))
    jobs = respx.get(EVADR_JOB)
    assert client.evadr.fetch(PAGE["url"]).html == "<html></html>"
    assert not jobs.called


@respx.mock
def test_a_202_is_followed_to_the_result(client: Kloakd) -> None:
    respx.post(f"{BASE}/evadr/fetch").mock(return_value=mock_response(HANDED_OFF, 202))
    respx.get(EVADR_JOB).mock(side_effect=[
        mock_response({"job_id": "job-1", "status": "running"}),
        mock_response({"job_id": "job-1", "status": "completed", "result": PAGE}),
    ])
    r = client.evadr.fetch(PAGE["url"], poll_interval=0.001)
    assert (r.ok, r.tier_used, r.html) == (True, 3, "<html></html>")


@respx.mock
def test_a_failed_job_raises_with_its_id(client: Kloakd) -> None:
    respx.post(f"{BASE}/evadr/fetch").mock(return_value=mock_response(HANDED_OFF, 202))
    respx.get(EVADR_JOB).mock(return_value=mock_response({"job_id": "job-1", "status": "failed", "error": "all attempts blocked"}))
    with pytest.raises(JobFailedError) as caught:
        client.evadr.fetch(PAGE["url"], poll_interval=0.001)
    assert (caught.value.job_id, caught.value.message) == ("job-1", "all attempts blocked")


@respx.mock
def test_following_stops_at_the_timeout(client: Kloakd) -> None:
    respx.post(f"{BASE}/evadr/fetch").mock(return_value=mock_response(HANDED_OFF, 202))
    respx.get(EVADR_JOB).mock(return_value=mock_response({"job_id": "job-1", "status": "running"}))
    with pytest.raises(JobTimeoutError):
        client.evadr.fetch(PAGE["url"], poll_interval=0.005, poll_timeout=0.008)


@respx.mock
def test_wait_for_job_polls_the_evadr_job_route(client: Kloakd) -> None:
    jobs = respx.get(EVADR_JOB).mock(return_value=mock_response({"job_id": "job-1", "status": "completed", "result": PAGE}))
    assert client.evadr.wait_for_job("job-1", poll_interval=0.001) == PAGE
    assert jobs.call_count == 1


@respx.mock
def test_fetch_async_uses_the_async_route(client: Kloakd) -> None:
    route = respx.post(f"{BASE}/evadr/fetch/async").mock(return_value=mock_response({"job_id": "job-2", "status": "pending", "message": ""}, 202))
    assert client.evadr.fetch_async(PAGE["url"], webhook_url="https://hooks.example/x") == "job-2"
    assert json.loads(route.calls.last.request.content) == {"url": PAGE["url"], "webhook_url": "https://hooks.example/x"}


@respx.mock
async def test_the_async_client_follows_a_202_too() -> None:
    respx.post(f"{BASE}/evadr/fetch").mock(return_value=mock_response(HANDED_OFF, 202))
    respx.get(EVADR_JOB).mock(return_value=mock_response({"job_id": "job-1", "status": "completed", "result": PAGE}))
    client = AsyncKloakd(api_key="k", organization_id=TEST_ORG_ID, base_url=TEST_BASE_URL)
    r = await client.evadr.fetch(PAGE["url"], poll_interval=0.001)
    assert r.tier_used == 3


@respx.mock
async def test_the_async_client_raises_on_expiry_and_timeout(fast_async_client: AsyncKloakd) -> None:
    respx.post(f"{BASE}/nexus/synthesize").mock(return_value=mock_response(handed_off(), 202))
    respx.get(HANDOFF_JOB).mock(side_effect=[Response(404, json={"detail": "gone"}), Response(401, json={"detail": "bad"})])
    with pytest.raises(JobFailedError):
        await fast_async_client.nexus.synthesize("https://x.example", "<html/>", "g")
    with pytest.raises(KloakdError):
        await fast_async_client.nexus.synthesize("https://x.example", "<html/>", "g")
    slow = AsyncKloakd(api_key="k", organization_id=TEST_ORG_ID, base_url=TEST_BASE_URL, poll_interval=0.005, poll_timeout=0.008)
    respx.get(HANDOFF_JOB).mock(return_value=running())
    with pytest.raises(JobTimeoutError):
        await slow.nexus.synthesize("https://x.example", "<html/>", "g")
