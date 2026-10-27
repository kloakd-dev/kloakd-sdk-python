"""Every request the SDK makes is a live API route (method and path).

tests/fixtures/routes.tsv is the backend's route list (METHOD\\tPATH,
generated from kobe-scraper 4fb33ea4 with the module routers mounted as
kernel/bootstrap.py does). Each public method of each namespace, sync and
async, is called with placeholder arguments against a recording mock.
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
