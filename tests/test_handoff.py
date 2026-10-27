"""The synchronous fetch answers within ~85 s; past that the API returns 202
and the fetch continues as a job (Cloudflare closes requests at 100 s)."""

from __future__ import annotations

import json

import pytest
import respx

from kloakd import AsyncKloakd, JobFailedError, JobTimeoutError, Kloakd
from tests.conftest import ORG_PREFIX, TEST_BASE_URL, TEST_ORG_ID, mock_response

BASE = f"{TEST_BASE_URL}{ORG_PREFIX}"
PAGE = {"success": True, "url": "https://www.economist.com/", "status_code": 200, "tier_used": 3, "html": "<html></html>", "error": None}
HANDED_OFF = {"job_id": "job-1", "status": "running", "reason": "sync_limit_reached", "waited_seconds": 85, "poll_url": "/x/evadr/jobs/job-1", "message": ""}


@respx.mock
def test_answered_in_time_is_the_page(client: Kloakd) -> None:
    respx.post(f"{BASE}/evadr/fetch").mock(return_value=mock_response(PAGE))
    jobs = respx.get(f"{BASE}/evadr/jobs/job-1")
    assert client.evadr.fetch(PAGE["url"]).html == "<html></html>"
    assert not jobs.called


@respx.mock
def test_a_202_is_followed_to_the_result(client: Kloakd) -> None:
    respx.post(f"{BASE}/evadr/fetch").mock(return_value=mock_response(HANDED_OFF, 202))
    respx.get(f"{BASE}/evadr/jobs/job-1").mock(side_effect=[
        mock_response({"job_id": "job-1", "status": "running"}),
        mock_response({"job_id": "job-1", "status": "completed", "result": PAGE}),
    ])
    r = client.evadr.fetch(PAGE["url"], poll_interval=0.001)
    assert (r.ok, r.tier_used, r.html) == (True, 3, "<html></html>")


@respx.mock
def test_a_failed_job_raises_with_its_id(client: Kloakd) -> None:
    respx.post(f"{BASE}/evadr/fetch").mock(return_value=mock_response(HANDED_OFF, 202))
    respx.get(f"{BASE}/evadr/jobs/job-1").mock(return_value=mock_response({"job_id": "job-1", "status": "failed", "error": "all attempts blocked"}))
    with pytest.raises(JobFailedError) as caught:
        client.evadr.fetch(PAGE["url"], poll_interval=0.001)
    assert (caught.value.job_id, caught.value.message) == ("job-1", "all attempts blocked")


@respx.mock
def test_following_stops_at_the_timeout(client: Kloakd) -> None:
    respx.post(f"{BASE}/evadr/fetch").mock(return_value=mock_response(HANDED_OFF, 202))
    respx.get(f"{BASE}/evadr/jobs/job-1").mock(return_value=mock_response({"job_id": "job-1", "status": "running"}))
    with pytest.raises(JobTimeoutError):
        client.evadr.fetch(PAGE["url"], poll_interval=0.005, poll_timeout=0.008)


@respx.mock
def test_fetch_async_uses_the_async_route(client: Kloakd) -> None:
    route = respx.post(f"{BASE}/evadr/fetch/async").mock(return_value=mock_response({"job_id": "job-2", "status": "pending", "message": ""}, 202))
    assert client.evadr.fetch_async(PAGE["url"], webhook_url="https://hooks.example/x") == "job-2"
    assert json.loads(route.calls.last.request.content) == {"url": PAGE["url"], "webhook_url": "https://hooks.example/x"}


@respx.mock
async def test_the_async_client_follows_a_202_too() -> None:
    respx.post(f"{BASE}/evadr/fetch").mock(return_value=mock_response(HANDED_OFF, 202))
    respx.get(f"{BASE}/evadr/jobs/job-1").mock(return_value=mock_response({"job_id": "job-1", "status": "completed", "result": PAGE}))
    client = AsyncKloakd(api_key="k", organization_id=TEST_ORG_ID, base_url=TEST_BASE_URL)
    r = await client.evadr.fetch(PAGE["url"], poll_interval=0.001)
    assert r.tier_used == 3
