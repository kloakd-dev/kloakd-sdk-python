"""Batch jobs and the unified scrape, each against the shape kobe-scraper's
code sends or reads.

Backend references are paths under kobe-scraper src/kobe_scraper/
(integration/2026-11-12b at 228857dc): kernel/jobs_runs_router.py,
application/jobs/batch_control.py, api/v1/endpoints/unified_scraping.py and
kernel/sync_handoff.py.
"""

from __future__ import annotations

import json
from typing import Any, Dict

import pytest
import respx
from httpx import Response

from kloakd import (
    ApiError,
    AsyncKloakd,
    BatchJob,
    BatchJobItem,
    BatchJobResults,
    BatchJobsPage,
    ConcurrencyLimitError,
    ForbiddenError,
    JobFailedError,
    Kloakd,
    UnifiedEscalation,
    UnifiedScrapeProgress,
    UnifiedScrapeResult,
    UnifiedScrapeStatus,
)
from tests.conftest import ORG_PREFIX, TEST_BASE_URL, TEST_ORG_ID, mock_response
from tests.test_contract import ROUTES, _live

BASE = f"{TEST_BASE_URL}{ORG_PREFIX}"
JOBS = f"{BASE}/batch-jobs"
BATCH = "b1"
UNIFIED = f"{BASE}/scraping/unified"
# application/jobs/batch_control.py PAUSED_MESSAGE
PAUSED_MESSAGE = (
    "paused: items that were already running finish; "
    "the rest wait until the batch is resumed."
)
CONTROLS = ("pause", "resume", "cancel")


@pytest.fixture
def client() -> Kloakd:
    return Kloakd(
        api_key="sk-live-k",
        organization_id=TEST_ORG_ID,
        base_url=TEST_BASE_URL,
        poll_interval=0.001,
    )


@pytest.fixture
def aclient() -> AsyncKloakd:
    return AsyncKloakd(
        api_key="sk-live-k",
        organization_id=TEST_ORG_ID,
        base_url=TEST_BASE_URL,
        poll_interval=0.001,
    )


def _body(route: Any, i: int = -1) -> Any:
    return json.loads(route.calls[i].request.content)


def _batch(status: str = "running", **over: Any) -> Dict[str, Any]:
    # kernel/jobs_runs_router.py BatchJob
    return {
        "id": BATCH,
        "name": "Batch 2 URLs",
        "status": status,
        "total_items": 2,
        "completed_items": 0,
        "created_at": "2026-11-12T10:00:00+00:00",
        "message": None,
        **over,
    }


def _refused(action: str, status: str, message: str) -> Response:
    # kernel/jobs_runs_router.py _batch_transition_refused
    return mock_response(
        {
            "detail": {
                "error": "invalid_batch_transition",
                "message": message,
                "action": action,
                "status": status,
            }
        },
        409,
    )


def _control(c: Any, action: str) -> Any:
    return getattr(c, f"{action}_batch_job")


# ── Create ─────────────────────────────────────────────────────────────


@respx.mock
def test_create_batch_job_sends_the_urls_and_only_the_fields_given(
    client: Kloakd,
) -> None:
    route = respx.post(JOBS).mock(return_value=mock_response(_batch("pending"), 201))
    job = client.create_batch_job(["https://a.example", "https://b.example"])
    assert _body(route) == {"urls": ["https://a.example", "https://b.example"]}
    assert job == BatchJob(
        id=BATCH,
        name="Batch 2 URLs",
        status="pending",
        total_items=2,
        completed_items=0,
        created_at="2026-11-12T10:00:00+00:00",
        message=None,
    )


@respx.mock
def test_create_batch_job_sends_every_field_the_route_reads(client: Kloakd) -> None:
    route = respx.post(JOBS).mock(return_value=mock_response(_batch(), 201))
    client.create_batch_job(
        ["https://a.example"],
        extraction_config={"selectors": {"title": "h1"}},
        crawl_id="c1",
        entity_type="product",
        fields=["title", "price"],
    )
    assert _body(route) == {
        "urls": ["https://a.example"],
        "extraction_config": {"selectors": {"title": "h1"}},
        "crawl_id": "c1",
        "entity_type": "product",
        "fields": ["title", "price"],
    }


@respx.mock
def test_create_batch_job_refusals_carry_the_api_code(client: Kloakd) -> None:
    route = respx.post(JOBS).mock(
        side_effect=[
            mock_response(
                {
                    "detail": {
                        "error": "test_key_not_allowed",
                        "message": "Batch jobs need a live API key.",
                    }
                },
                403,
            ),
            mock_response(
                {
                    "detail": {
                        "error": "batch_too_large",
                        "message": "Your plan allows 100 URLs per batch.",
                        "tier": "free",
                        "max_items": 100,
                        "requested_items": 101,
                    }
                },
                413,
            ),
            mock_response(
                {
                    "detail": {
                        "error": "concurrent_limit",
                        "message": "Your plan runs 2 batches at once.",
                        "tier": "free",
                        "concurrent_limit": 2,
                        "active_batches": 2,
                    }
                },
                409,
            ),
        ]
    )
    with pytest.raises(ForbiddenError) as forbidden:
        client.create_batch_job(["https://a.example"])
    assert forbidden.value.code == "test_key_not_allowed"
    with pytest.raises(ApiError) as too_large:
        client.create_batch_job(["https://a.example"])
    assert (too_large.value.status_code, too_large.value.code) == (
        413,
        "batch_too_large",
    )
    with pytest.raises(ConcurrencyLimitError) as full:
        client.create_batch_job(["https://a.example"])
    assert (full.value.concurrent_limit, full.value.tier) == (2, "free")
    assert route.call_count == 3


@respx.mock
def test_a_batch_that_could_not_be_queued_is_503_and_is_not_retried(
    client: Kloakd,
) -> None:
    route = respx.post(JOBS).mock(
        return_value=mock_response(
            {
                "detail": {
                    "error": "dispatch_failed",
                    "message": "The batch could not be queued.",
                    "batch_job_id": BATCH,
                }
            },
            503,
        )
    )
    with pytest.raises(ApiError) as caught:
        client.create_batch_job(["https://a.example"])
    assert (caught.value.status_code, caught.value.code) == (503, "dispatch_failed")
    assert route.call_count == 1


# ── Read ───────────────────────────────────────────────────────────────


@respx.mock
def test_get_batch_job_reads_the_state(client: Kloakd) -> None:
    respx.get(f"{JOBS}/{BATCH}").mock(
        return_value=mock_response(
            _batch("paused", completed_items=1, message=PAUSED_MESSAGE)
        )
    )
    job = client.get_batch_job(BATCH)
    assert (job.status, job.completed_items, job.message) == (
        "paused",
        1,
        PAUSED_MESSAGE,
    )


@respx.mock
def test_a_batch_that_is_not_yours_is_404(client: Kloakd) -> None:
    respx.get(f"{JOBS}/nope").mock(
        return_value=mock_response({"detail": "Batch job not found"}, 404)
    )
    with pytest.raises(ApiError) as caught:
        client.get_batch_job("nope")
    assert caught.value.status_code == 404


@respx.mock
def test_list_batch_jobs_pages(client: Kloakd) -> None:
    route = respx.get(JOBS).mock(
        return_value=mock_response(
            {"total": 7, "batch_jobs": [_batch(), _batch("completed", id="b0")]}
        )
    )
    page = client.list_batch_jobs()
    assert dict(route.calls.last.request.url.params) == {}
    assert isinstance(page, BatchJobsPage) and page.total == 7
    assert [(j.id, j.status) for j in page.batch_jobs] == [
        (BATCH, "running"),
        ("b0", "completed"),
    ]
    client.list_batch_jobs(page=2, page_size=50)
    assert dict(route.calls.last.request.url.params) == {"page": "2", "page_size": "50"}


@respx.mock
def test_get_batch_job_results_lists_the_items(client: Kloakd) -> None:
    route = respx.get(f"{JOBS}/{BATCH}/results").mock(
        return_value=mock_response(
            {
                "batch_job_id": BATCH,
                "results": [
                    {
                        "job_id": "j1",
                        "url": "https://a.example",
                        "status": "completed",
                        "extracted_data": [{"title": "A"}],
                        "api_data": {"records": [{"id": 1}]},
                    },
                    {
                        "job_id": "j2",
                        "url": "https://b.example",
                        "status": "failed",
                        "extracted_data": None,
                    },
                ],
                "total_jobs": 2,
                "completed_jobs": 1,
                "failed_jobs": 1,
            }
        )
    )
    results = client.get_batch_job_results(BATCH)
    assert dict(route.calls.last.request.url.params) == {}
    assert results == BatchJobResults(
        batch_job_id=BATCH,
        results=[
            BatchJobItem(
                job_id="j1",
                url="https://a.example",
                status="completed",
                extracted_data=[{"title": "A"}],
                api_data={"records": [{"id": 1}]},
            ),
            BatchJobItem(job_id="j2", url="https://b.example", status="failed"),
        ],
        total_jobs=2,
        completed_jobs=1,
        failed_jobs=1,
    )
    client.get_batch_job_results(BATCH, limit=100, offset=200)
    assert dict(route.calls.last.request.url.params) == {
        "limit": "100",
        "offset": "200",
    }


# ── Pause, resume, cancel ──────────────────────────────────────────────


@pytest.mark.parametrize(
    ("action", "status", "message"),
    [("pause", "paused", PAUSED_MESSAGE), ("resume", "running", None), ("cancel", "cancelled", None)],
    ids=CONTROLS,
)
@respx.mock
def test_a_control_posts_an_empty_body_and_returns_the_batch(
    client: Kloakd, action: str, status: str, message: Any
) -> None:
    route = respx.post(f"{JOBS}/{BATCH}/{action}").mock(
        return_value=mock_response(_batch(status, message=message))
    )
    job = _control(client, action)(BATCH)
    assert _body(route) == {}
    assert (job.id, job.status, job.message) == (BATCH, status, message)


@pytest.mark.parametrize(
    ("action", "status"),
    [("pause", "paused"), ("resume", "running"), ("cancel", "cancelled")],
    ids=CONTROLS,
)
@respx.mock
def test_repeating_a_control_is_200_and_not_an_error(
    client: Kloakd, action: str, status: str
) -> None:
    # batch_control.py: a repeat returns the batch unchanged.
    route = respx.post(f"{JOBS}/{BATCH}/{action}").mock(
        return_value=mock_response(_batch(status))
    )
    first = _control(client, action)(BATCH)
    second = _control(client, action)(BATCH)
    assert first == second and second.status == status
    assert route.call_count == 2


@pytest.mark.parametrize(
    ("action", "status", "message"),
    [
        ("pause", "completed", "Only a running batch can be paused (current status: completed)."),
        ("resume", "cancelled", "Only a paused batch can be resumed (current status: cancelled)."),
        ("cancel", "completed", "A batch that has completed cannot be cancelled."),
    ],
    ids=CONTROLS,
)
@respx.mock
def test_a_refused_control_is_409_invalid_batch_transition(
    client: Kloakd, action: str, status: str, message: str
) -> None:
    route = respx.post(f"{JOBS}/{BATCH}/{action}").mock(
        return_value=_refused(action, status, message)
    )
    with pytest.raises(ApiError) as caught:
        _control(client, action)(BATCH)
    error = caught.value
    assert (error.status_code, error.code) == (409, "invalid_batch_transition")
    assert not isinstance(error, ConcurrencyLimitError)
    assert message in error.message
    assert route.call_count == 1


@respx.mock
def test_resume_that_cannot_queue_is_503_dispatch_failed_and_is_not_retried(
    client: Kloakd,
) -> None:
    route = respx.post(f"{JOBS}/{BATCH}/resume").mock(
        return_value=mock_response(
            {
                "detail": {
                    "error": "dispatch_failed",
                    "message": "The batch could not be resumed; it is paused again.",
                    "batch_job_id": BATCH,
                    "items_not_queued": 2,
                }
            },
            503,
        )
    )
    with pytest.raises(ApiError) as caught:
        client.resume_batch_job(BATCH)
    assert (caught.value.status_code, caught.value.code) == (503, "dispatch_failed")
    assert "paused again" in caught.value.message
    assert route.call_count == 1


@respx.mock
def test_resume_at_the_running_batch_limit_is_a_concurrency_limit_error(
    client: Kloakd,
) -> None:
    respx.post(f"{JOBS}/{BATCH}/resume").mock(
        return_value=mock_response(
            {
                "detail": {
                    "error": "concurrent_limit",
                    "message": "Your plan runs 2 batches at once.",
                    "tier": "free",
                    "concurrent_limit": 2,
                    "active_batches": 2,
                }
            },
            409,
        )
    )
    with pytest.raises(ConcurrencyLimitError) as caught:
        client.resume_batch_job(BATCH)
    assert caught.value.code == "concurrent_limit"
    assert caught.value.concurrent_limit == 2
    # detail.active_batches (kernel/jobs_runs_router.py _check_batch_concurrency)
    assert caught.value.active_crawls == 2
    assert caught.value.tier == "free"


@respx.mock
def test_a_control_on_a_batch_that_is_not_yours_is_404(client: Kloakd) -> None:
    for action in CONTROLS:
        respx.post(f"{JOBS}/nope/{action}").mock(
            return_value=mock_response({"detail": "Batch job not found"}, 404)
        )
        with pytest.raises(ApiError) as caught:
            _control(client, action)("nope")
        assert caught.value.status_code == 404


@respx.mock
def test_a_batch_id_is_one_path_segment(client: Kloakd) -> None:
    route = respx.post(url__regex=r".*/batch-jobs/.*").mock(
        return_value=mock_response(_batch("paused"))
    )
    client.pause_batch_job("a/b")
    assert route.calls.last.request.url.raw_path.endswith(b"/batch-jobs/a%2Fb/pause")


# ── Unified scrape ─────────────────────────────────────────────────────


def _unified(**over: Any) -> Dict[str, Any]:
    # api/v1/endpoints/unified_scraping.py UnifiedScrapeResponse
    return {
        "success": True,
        "job_id": "u1",
        "level": "level2",
        "status": "completed",
        "escalation_path": [
            {
                "from": "level1",
                "to": "level2",
                "reason": "no records",
                "timestamp": "2026-11-12T10:00:01+00:00",
            }
        ],
        "message": "Scrape completed.",
        "metadata": {"records": 3},
        "auth_required": False,
        "discovery_id": None,
        **over,
    }


@respx.mock
def test_unified_scrape_sends_the_url_alone_by_default(client: Kloakd) -> None:
    route = respx.post(UNIFIED).mock(return_value=mock_response(_unified()))
    result = client.unified_scrape("https://x.example")
    assert _body(route) == {"url": "https://x.example"}
    assert result == UnifiedScrapeResult(
        success=True,
        job_id="u1",
        level="level2",
        status="completed",
        escalation_path=[
            UnifiedEscalation(
                from_level="level1",
                to_level="level2",
                reason="no records",
                timestamp="2026-11-12T10:00:01+00:00",
            )
        ],
        message="Scrape completed.",
        metadata={"records": 3},
        auth_required=False,
        discovery_id=None,
    )


@respx.mock
def test_unified_scrape_sends_every_field_the_route_reads(client: Kloakd) -> None:
    route = respx.post(UNIFIED).mock(return_value=mock_response(_unified()))
    client.unified_scrape(
        "https://x.example",
        prompt="the prices",
        mode="level2",
        schema={"price": "the product's price"},
        options={"max_pages": 2},
        context={"site": "shop"},
        constraints={"max_seconds": 60},
        session_artifact_id="art-1",
    )
    assert _body(route) == {
        "url": "https://x.example",
        "prompt": "the prices",
        "mode": "level2",
        "schema": {"price": "the product's price"},
        "options": {"max_pages": 2},
        "context": {"site": "shop"},
        "constraints": {"max_seconds": 60},
        "session_artifact_id": "art-1",
    }


@respx.mock
def test_unified_scrape_reports_a_login_wall(client: Kloakd) -> None:
    # unified_scraping.py: the preflight answer when the URL is behind a login.
    respx.post(UNIFIED).mock(
        return_value=mock_response(
            _unified(
                level="preflight",
                status="auth_required",
                escalation_path=[],
                message="This page needs a login.",
                metadata=None,
                auth_required=True,
                discovery_id="d1",
            )
        )
    )
    result = client.unified_scrape("https://x.example/account")
    assert (result.level, result.status) == ("preflight", "auth_required")
    assert (result.auth_required, result.discovery_id) == (True, "d1")
    assert result.escalation_path == [] and result.metadata is None


@respx.mock
def test_unified_scrape_follows_a_202_hand_off(client: Kloakd) -> None:
    # kernel/sync_handoff.py: the 202 body and GET handoff/{job_id}.
    post = respx.post(UNIFIED).mock(
        return_value=mock_response(
            {
                "job_id": "h-1",
                "status": "running",
                "reason": "sync_limit_reached",
                "waited_seconds": 85.0,
                "poll_url": f"{ORG_PREFIX}/handoff/h-1",
                "message": "Still running; it continues as a job.",
            },
            202,
        )
    )
    poll = respx.get(f"{BASE}/handoff/h-1").mock(
        side_effect=[
            mock_response({"job_id": "h-1", "kind": "x", "status": "running"}),
            mock_response(
                {
                    "job_id": "h-1",
                    "kind": "x",
                    "status": "completed",
                    "result": _unified(),
                }
            ),
        ]
    )
    result = client.unified_scrape("https://x.example", poll_interval=0.001)
    assert (result.job_id, result.level, result.status) == ("u1", "level2", "completed")
    assert post.call_count == 1 and poll.call_count == 2


@respx.mock
def test_a_handed_off_unified_scrape_that_fails_raises_job_failed(
    client: Kloakd,
) -> None:
    respx.post(UNIFIED).mock(
        return_value=mock_response(
            {
                "job_id": "h-1",
                "status": "running",
                "poll_url": f"{ORG_PREFIX}/handoff/h-1",
            },
            202,
        )
    )
    respx.get(f"{BASE}/handoff/h-1").mock(
        return_value=mock_response(
            {"job_id": "h-1", "status": "failed", "error": "Scrape failed: boom"}
        )
    )
    with pytest.raises(JobFailedError) as caught:
        client.unified_scrape("https://x.example", poll_interval=0.001)
    assert (caught.value.job_id, caught.value.message) == ("h-1", "Scrape failed: boom")


@pytest.mark.parametrize("code", ["test_key_not_allowed", "module_not_entitled"])
@respx.mock
def test_unified_scrape_refusals_are_forbidden_with_the_api_code(
    client: Kloakd, code: str
) -> None:
    # unified_scraping.py unified_scrape_access
    respx.post(UNIFIED).mock(
        return_value=mock_response(
            {"detail": {"error": code, "message": "Not allowed."}}, 403
        )
    )
    with pytest.raises(ForbiddenError) as caught:
        client.unified_scrape("https://x.example")
    assert caught.value.code == code


@respx.mock
def test_unified_scrape_is_not_retried_on_a_server_error(client: Kloakd) -> None:
    route = respx.post(UNIFIED).mock(
        return_value=mock_response({"detail": "boom"}, 500)
    )
    with pytest.raises(ApiError):
        client.unified_scrape("https://x.example")
    assert route.call_count == 1


@respx.mock
def test_get_unified_scrape_reads_a_running_job(client: Kloakd) -> None:
    # unified_scraping.py JobStatusResponse and ProgressDetail
    respx.get(f"{UNIFIED}/u1").mock(
        return_value=mock_response(
            {
                "id": "u1",
                "status": "running",
                "level": "level1",
                "progress": 40,
                "progress_detail": {
                    "percentage": 40,
                    "current_step": "extracting",
                    "items_found": 4,
                    "items_target": 10,
                    "partial_results": [{"title": "A"}],
                },
                "created_at": "2026-11-12T10:00:00+00:00",
                "updated_at": "2026-11-12T10:00:05+00:00",
                "completed_at": None,
                "error": None,
                "result": None,
                "escalation_path": [],
            }
        )
    )
    status = client.get_unified_scrape("u1")
    assert status == UnifiedScrapeStatus(
        id="u1",
        status="running",
        level="level1",
        progress=40,
        progress_detail=UnifiedScrapeProgress(
            percentage=40,
            current_step="extracting",
            items_found=4,
            items_target=10,
            partial_results=[{"title": "A"}],
        ),
        created_at="2026-11-12T10:00:00+00:00",
        updated_at="2026-11-12T10:00:05+00:00",
    )


@respx.mock
def test_get_unified_scrape_reads_a_finished_job(client: Kloakd) -> None:
    respx.get(f"{UNIFIED}/u1").mock(
        return_value=mock_response(
            {
                "id": "u1",
                "status": "completed",
                "level": "level2",
                "progress": 100,
                "progress_detail": None,
                "created_at": "2026-11-12T10:00:00+00:00",
                "updated_at": "2026-11-12T10:01:00+00:00",
                "completed_at": "2026-11-12T10:01:00+00:00",
                "error": None,
                "result": {"data": [{"price": "9.99"}]},
                "escalation_path": [
                    {"from": "level1", "to": "level2", "reason": "blocked", "timestamp": "t"}
                ],
            }
        )
    )
    status = client.get_unified_scrape("u1")
    assert status.progress_detail is None
    assert status.result == {"data": [{"price": "9.99"}]}
    assert status.completed_at == "2026-11-12T10:01:00+00:00"
    assert [(e.from_level, e.to_level, e.reason) for e in status.escalation_path] == [
        ("level1", "level2", "blocked")
    ]


@respx.mock
def test_a_unified_scrape_job_that_is_not_yours_is_404(client: Kloakd) -> None:
    respx.get(f"{UNIFIED}/nope").mock(
        return_value=mock_response({"detail": "Job nope not found"}, 404)
    )
    with pytest.raises(ApiError) as caught:
        client.get_unified_scrape("nope")
    assert caught.value.status_code == 404


# ── The async client ───────────────────────────────────────────────────


@respx.mock
async def test_the_async_client_runs_a_batch(aclient: AsyncKloakd) -> None:
    create = respx.post(JOBS).mock(return_value=mock_response(_batch("pending"), 201))
    respx.get(f"{JOBS}/{BATCH}").mock(return_value=mock_response(_batch()))
    listing = respx.get(JOBS).mock(
        return_value=mock_response({"total": 1, "batch_jobs": [_batch()]})
    )
    results = respx.get(f"{JOBS}/{BATCH}/results").mock(
        return_value=mock_response(
            {
                "batch_job_id": BATCH,
                "results": [{"job_id": "j1", "url": "https://a.example", "status": "running"}],
                "total_jobs": 2,
                "completed_jobs": 0,
                "failed_jobs": 0,
            }
        )
    )
    respx.post(f"{JOBS}/{BATCH}/pause").mock(
        return_value=mock_response(_batch("paused", message=PAUSED_MESSAGE))
    )
    respx.post(f"{JOBS}/{BATCH}/resume").mock(return_value=mock_response(_batch()))
    respx.post(f"{JOBS}/{BATCH}/cancel").mock(
        return_value=mock_response(_batch("cancelled"))
    )

    job = await aclient.create_batch_job(["https://a.example"], fields=["title"])
    assert _body(create) == {"urls": ["https://a.example"], "fields": ["title"]}
    assert job.status == "pending"
    assert (await aclient.get_batch_job(BATCH)).status == "running"
    page = await aclient.list_batch_jobs(page=1, page_size=10)
    assert dict(listing.calls.last.request.url.params) == {"page": "1", "page_size": "10"}
    assert page.total == 1 and page.batch_jobs[0].id == BATCH
    items = await aclient.get_batch_job_results(BATCH, limit=1)
    assert dict(results.calls.last.request.url.params) == {"limit": "1"}
    assert (items.total_jobs, items.results[0].job_id) == (2, "j1")
    paused = await aclient.pause_batch_job(BATCH)
    assert (paused.status, paused.message) == ("paused", PAUSED_MESSAGE)
    assert (await aclient.pause_batch_job(BATCH)).status == "paused"
    assert (await aclient.resume_batch_job(BATCH)).status == "running"
    assert (await aclient.cancel_batch_job(BATCH)).status == "cancelled"


@respx.mock
async def test_the_async_client_raises_the_same_batch_errors(
    aclient: AsyncKloakd,
) -> None:
    respx.post(f"{JOBS}/{BATCH}/pause").mock(
        return_value=_refused(
            "pause",
            "completed",
            "Only a running batch can be paused (current status: completed).",
        )
    )
    resume = respx.post(f"{JOBS}/{BATCH}/resume").mock(
        return_value=mock_response(
            {
                "detail": {
                    "error": "dispatch_failed",
                    "message": "The batch could not be resumed; it is paused again.",
                    "batch_job_id": BATCH,
                    "items_not_queued": 2,
                }
            },
            503,
        )
    )
    with pytest.raises(ApiError) as refused:
        await aclient.pause_batch_job(BATCH)
    assert (refused.value.status_code, refused.value.code) == (
        409,
        "invalid_batch_transition",
    )
    with pytest.raises(ApiError) as failed:
        await aclient.resume_batch_job(BATCH)
    assert (failed.value.status_code, failed.value.code) == (503, "dispatch_failed")
    assert resume.call_count == 1


@respx.mock
async def test_the_async_client_scrapes_and_follows_a_hand_off(
    aclient: AsyncKloakd,
) -> None:
    post = respx.post(UNIFIED).mock(
        side_effect=[
            mock_response(_unified()),
            mock_response(
                {
                    "job_id": "h-1",
                    "status": "running",
                    "poll_url": f"{ORG_PREFIX}/handoff/h-1",
                },
                202,
            ),
        ]
    )
    respx.get(f"{BASE}/handoff/h-1").mock(
        return_value=mock_response(
            {"job_id": "h-1", "status": "completed", "result": _unified(job_id="u2")}
        )
    )
    respx.get(f"{UNIFIED}/u2").mock(
        return_value=mock_response({"id": "u2", "status": "completed", "level": "level2"})
    )
    first = await aclient.unified_scrape("https://x.example", prompt="the prices")
    assert _body(post, 0) == {"url": "https://x.example", "prompt": "the prices"}
    assert first.job_id == "u1"
    second = await aclient.unified_scrape("https://x.example", poll_interval=0.001)
    assert second.job_id == "u2"
    status = await aclient.get_unified_scrape("u2")
    assert (status.id, status.status, status.progress) == ("u2", "completed", None)


# ── The route list ─────────────────────────────────────────────────────

NEW_ROUTES = [
    ("POST", "batch-jobs"),
    ("GET", "batch-jobs"),
    ("GET", "batch-jobs/b1"),
    ("GET", "batch-jobs/b1/results"),
    ("POST", "batch-jobs/b1/pause"),
    ("POST", "batch-jobs/b1/resume"),
    ("POST", "batch-jobs/b1/cancel"),
    ("POST", "scraping/unified"),
    ("GET", "scraping/unified/u1"),
]


def test_the_new_methods_call_live_routes() -> None:
    assert [r for r in NEW_ROUTES if not _live(r[0], f"{ORG_PREFIX}/{r[1]}")] == []
    client = Kloakd(api_key="k", organization_id=TEST_ORG_ID, base_url=TEST_BASE_URL)
    with respx.mock(assert_all_called=False) as router:
        router.route().mock(
            side_effect=lambda request: Response(
                200, json={"id": "b1", "job_id": "u1", "status": "running"}
            )
        )
        client.create_batch_job(["https://a.example"])
        client.list_batch_jobs()
        client.get_batch_job("b1")
        client.get_batch_job_results("b1")
        client.pause_batch_job("b1")
        client.resume_batch_job("b1")
        client.cancel_batch_job("b1")
        client.unified_scrape("https://x.example")
        client.get_unified_scrape("u1")
        called = [
            (c.request.method, c.request.url.path[len(ORG_PREFIX) + 1 :])
            for c in router.calls
        ]
    assert called == NEW_ROUTES


def test_the_route_list_has_280_routes_and_no_performance_routes() -> None:
    # kobe-scraper integration/2026-11-12b (228857dc) removed its 12
    # performance/... routes; monitoring/performance is another route.
    assert len(ROUTES) == 280
    assert not _live("GET", f"{ORG_PREFIX}/performance/metrics")
    assert [p.pattern for _, p in ROUTES if "/performance/" in p.pattern] == []
