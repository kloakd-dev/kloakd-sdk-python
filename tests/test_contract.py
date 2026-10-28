"""Every request the SDK makes is a live API route (method and path).

tests/fixtures/routes.tsv is the backend's route list (METHOD\\tPATH,
generated from kobe-scraper 4fb33ea4 with the module routers mounted as
kernel/bootstrap.py does). Each public method of each namespace, sync and
async, is called with placeholder arguments against a recording mock.

0.4.0 edits to the list, from kobe-scraper's code: the 13
``nexus/recommendations/*`` routes and ``POST kolektr/jobs`` are deleted
(they returned invented results); the standalone ``recommendations/*``
router is not mounted (``api/app.py``, GAP-SEC-6); the kolektr job
progress, progress-phase and pipeline routes, ``webgrph/analytics/job-trends``
and ``error-summary`` and ``evadr/profiles`` are deleted (kobe-scraper
d7d25134, invented results too); the hand-off poll
``GET …/handoff/{job_id}`` (``kernel/sync_handoff.py``) is added.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path
from typing import Any, List, Tuple

import respx
from httpx import Response

from kloakd import AsyncKloakd, Kloakd
from tests.conftest import ORG_PREFIX, TEST_BASE_URL, TEST_ORG_ID

NAMESPACES = ("evadr", "webgrph", "skanyr", "nexus", "parlyr", "fetchyr", "kolektr")
GENERIC = {"status": "completed", "crawl_id": "c-1", "job_id": "j-1", "nodes": [], "next_cursor": None, "result": {}, "success": True}


def _routes() -> List[Tuple[str, re.Pattern[str]]]:
    out = []
    for line in (Path(__file__).parent / "fixtures" / "routes.tsv").read_text().strip().splitlines():
        method, path = line.split("\t")
        pattern = re.escape(path)
        pattern = re.sub(r"\\\{[a-z_]+:path\\\}", ".+", pattern)
        pattern = re.sub(r"\\\{[a-z_]+\\\}", "[^/]+", pattern)
        out.append((method, re.compile(f"^{pattern}$")))
    return out


ROUTES = _routes()


def _live(method: str, path: str) -> bool:
    return any(m == method and p.match(path) for m, p in ROUTES)


def _public_methods(namespace: Any) -> List[str]:
    return [n for n, _ in inspect.getmembers(type(namespace), inspect.isfunction) if not n.startswith("_")]


def _args(fn: Any) -> List[Any]:
    params = [p for p in inspect.signature(fn).parameters.values() if p.name != "self"]
    out: List[Any] = []
    for p in params:
        if p.default is not inspect.Parameter.empty or p.kind in (p.VAR_KEYWORD, p.VAR_POSITIONAL):
            continue
        name = p.name
        if name in ("steps", "sites"):
            out.append([{"a": 1}])
        elif name in ("body", "data", "form_data", "metadata", "credentials"):
            out.append({"a": "b"})
        else:
            out.append(f"{name}-1")
    return out


def _recorded(router: respx.Router) -> List[Tuple[str, str]]:
    return [(c.request.method, c.request.url.path) for c in router.calls]


def _check(calls: List[Tuple[str, str, str]]) -> None:
    assert len(calls) > 80
    dead = [f"{who}: {m} {p}" for who, m, p in calls if not _live(m, p)]
    assert dead == []
    assert [p for _, _, p in calls if DASHBOARD_ONLY.search(p)] == []
    assert all(p.startswith(ORG_PREFIX) for _, _, p in calls)


def test_every_sync_request_is_a_live_route() -> None:
    client = Kloakd(api_key="k", organization_id=TEST_ORG_ID, base_url=TEST_BASE_URL, max_retries=1)
    calls: List[Tuple[str, str, str]] = []
    with respx.mock(assert_all_called=False) as router:
        router.route().mock(return_value=Response(200, json=GENERIC))
        for ns in NAMESPACES:
            namespace = getattr(client, ns)
            for name in _public_methods(namespace):
                fn = getattr(namespace, name)
                before = len(router.calls)
                try:
                    out = fn(*_args(fn))
                    if inspect.isgenerator(out):
                        list(out)
                except Exception:
                    pass  # placeholder arguments; the request sent is what is checked
                calls += [(f"{ns}.{name}", m, p) for m, p in _recorded(router)[before:]]
    _check(calls)


async def test_every_async_request_is_a_live_route() -> None:
    client = AsyncKloakd(api_key="k", organization_id=TEST_ORG_ID, base_url=TEST_BASE_URL, max_retries=1)
    calls: List[Tuple[str, str, str]] = []
    with respx.mock(assert_all_called=False) as router:
        router.route().mock(return_value=Response(200, json=GENERIC))
        for ns in NAMESPACES:
            namespace = getattr(client, ns)
            for name in _public_methods(namespace):
                fn = getattr(namespace, name)
                before = len(router.calls)
                try:
                    out = fn(*_args(fn))
                    if inspect.isasyncgen(out):
                        async for _ in out:
                            pass
                    elif hasattr(out, "__aenter__"):
                        async with out as events:
                            async for _ in events:
                                pass
                    elif inspect.isawaitable(out):
                        await out
                except Exception:
                    pass
                calls += [(f"{ns}.{name}", m, p) for m, p in _recorded(router)[before:]]
    _check(calls)


def test_sync_and_async_namespaces_offer_the_same_methods() -> None:
    sync_client = Kloakd(api_key="k", organization_id=TEST_ORG_ID)
    async_client = AsyncKloakd(api_key="k", organization_id=TEST_ORG_ID)
    for ns in NAMESPACES:
        assert set(_public_methods(getattr(sync_client, ns))) == set(_public_methods(getattr(async_client, ns))), ns


# The POST routes that answer 202 after the synchronous wait: the routes
# decorated with @hands_off_after_limit in kobe-scraper's module routers,
# and evadr/fetch, which hands off to its own job route.
HANDOFF_ROUTES = {
    "evadr/fetch",
    "kolektr/extract",
    "fetchyr/authenticate",
    "fetchyr/form/detect",
    "fetchyr/form/fill",
    "fetchyr/mfa/detect",
    "nexus/analyze",
    "nexus/synthesize",
    "nexus/execute",
}
# The methods expected to follow them (page_all goes through page).
FOLLOWERS = {
    "evadr.fetch", "kolektr.page", "kolektr.page_all", "fetchyr.authenticate",
    "fetchyr.detect_forms", "fetchyr.fill_form", "fetchyr.detect_mfa",
    "nexus.analyze", "nexus.synthesize", "nexus.execute",
}
DELETED = [
    ("POST", "kolektr/jobs"),
    *[(m, f"nexus/recommendations/{p}") for m, p in [
        ("GET", "statistics"), ("GET", "cache/statistics"), ("POST", "cache/cleanup"),
        ("POST", "cache/invalidate"), ("GET", "preferences/u-1"), ("POST", "preferences"),
        ("PUT", "preferences/p-1"), ("DELETE", "preferences/p-1"), ("GET", "applications"),
        ("GET", "hooks/status"), ("POST", "hooks/h/enable"), ("POST", "hooks/h/disable"),
        ("POST", "analyze"),
    ]],
    *[("GET", f"kolektr/{p}") for p in [
        "jobs/j/progress", "jobs/j/progress/summary", "jobs/j/progress/events",
        "jobs/j/progress/latest", "progress/phases", "progress/phases/x",
        "progress/phases/x/steps", "progress/summary", "pipeline/p/stream", "pipeline/p/events",
    ]],
    ("GET", "webgrph/analytics/job-trends"),
    ("GET", "webgrph/analytics/error-summary"),
    ("GET", "evadr/profiles"),
]
# The webgrph analytics sub-router serves the dashboard and is not part of
# the public API (kobe-scraper scripts/generate_public_openapi.py EXCLUDED);
# its routes exist but the SDK does not call them.
DASHBOARD_ONLY = re.compile(r"/webgrph/analytics/")


def _handoff_responder(request: Any) -> Response:
    path = request.url.path[len(ORG_PREFIX) + 1:]
    if request.method == "POST" and path in HANDOFF_ROUTES:
        job = "evadr/jobs/j-1" if path == "evadr/fetch" else "handoff/h-1"
        return Response(202, json={"job_id": "j-1", "status": "running", "poll_url": f"{ORG_PREFIX}/{job}"})
    return Response(200, json={**GENERIC, "status": "completed"})


def test_the_deleted_routes_are_not_in_the_route_list() -> None:
    assert len(DELETED) == 27
    assert [(m, p) for m, p in DELETED if _live(m, f"{ORG_PREFIX}/{p}")] == []
    assert _live("GET", f"{ORG_PREFIX}/handoff/h-1")
    assert all(_live("POST", f"{ORG_PREFIX}/{p}") for p in HANDOFF_ROUTES)


def test_exactly_the_hand_off_routes_are_followed_to_a_live_poll_route() -> None:
    client = Kloakd(api_key="k", organization_id=TEST_ORG_ID, base_url=TEST_BASE_URL, max_retries=1, poll_interval=0.0001)
    followed = set()
    with respx.mock(assert_all_called=False) as router:
        router.route().mock(side_effect=_handoff_responder)
        for ns in NAMESPACES:
            namespace = getattr(client, ns)
            for name in _public_methods(namespace):
                fn = getattr(namespace, name)
                before = len(router.calls)
                kwargs = {"poll_interval": 0.0001} if (ns, name) == ("evadr", "fetch") else {}
                try:
                    out = fn(*_args(fn), **kwargs)
                    if inspect.isgenerator(out):
                        list(out)
                except Exception:
                    pass
                calls = _recorded(router)[before:]
                polls = [p for m, p in calls if m == "GET" and (p.endswith("/handoff/h-1") or p.endswith("/evadr/jobs/j-1"))]
                if polls:
                    followed.add(f"{ns}.{name}")
                    assert all(_live("GET", p) for p in polls), (ns, name, polls)
    assert followed == FOLLOWERS


async def test_the_async_client_follows_the_same_routes() -> None:
    client = AsyncKloakd(api_key="k", organization_id=TEST_ORG_ID, base_url=TEST_BASE_URL, max_retries=1, poll_interval=0.0001)
    followed = set()
    with respx.mock(assert_all_called=False) as router:
        router.route().mock(side_effect=_handoff_responder)
        for ns in NAMESPACES:
            namespace = getattr(client, ns)
            for name in _public_methods(namespace):
                fn = getattr(namespace, name)
                before = len(router.calls)
                kwargs = {"poll_interval": 0.0001} if (ns, name) == ("evadr", "fetch") else {}
                try:
                    out = fn(*_args(fn), **kwargs)
                    if inspect.isasyncgen(out):
                        async for _ in out:
                            pass
                    elif inspect.isawaitable(out):
                        await out
                except Exception:
                    pass
                if any(m == "GET" and (p.endswith("/handoff/h-1") or p.endswith("/evadr/jobs/j-1")) for m, p in _recorded(router)[before:]):
                    followed.add(f"{ns}.{name}")
    assert followed == FOLLOWERS


def test_the_deleted_methods_are_gone() -> None:
    client = Kloakd(api_key="k", organization_id=TEST_ORG_ID)
    gone = ["recommend_analyze", "list_recommendation_applications", "get_cache_statistics",
            "cleanup_cache", "invalidate_cache", "get_hooks_status", "enable_hook", "disable_hook",
            "create_preference", "get_preferences", "update_preference", "delete_preference",
            "get_recommendation_statistics"]
    assert [n for n in gone if hasattr(client.nexus, n)] == []
    assert not hasattr(client.kolektr, "create_job")
    kolektr_gone = ["get_job_progress", "get_job_progress_events", "get_job_progress_latest",
                    "get_job_progress_summary", "get_pipeline_events", "get_pipeline_stream",
                    "list_progress_phases", "get_progress_phase", "get_progress_phase_steps",
                    "get_progress_summary"]
    assert [n for n in kolektr_gone if hasattr(client.kolektr, n)] == []
    webgrph_gone = ["get_dashboard_summary", "get_error_summary", "get_job_trends",
                    "get_discovery_patterns", "get_efficiency_metrics",
                    "get_site_mapping_trends", "get_user_behavior_insights"]
    assert [n for n in webgrph_gone if hasattr(client.webgrph, n)] == []
    assert not hasattr(client.evadr, "list_profiles")
    assert hasattr(client.evadr, "list_vendors")
    assert hasattr(client.kolektr, "get_job")
