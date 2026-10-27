"""Skanyr: the site knowledge store."""

from __future__ import annotations

import json

import respx

from kloakd import Kloakd
from tests.conftest import ORG_PREFIX, TEST_BASE_URL, mock_response

BASE = f"{TEST_BASE_URL}{ORG_PREFIX}"


@respx.mock
def test_site_from_crawl(client: Kloakd) -> None:
    route = respx.post(f"{BASE}/skanyr/sites/from-crawl/crawl-1").mock(return_value=mock_response({"id": "site-1"}))
    assert client.skanyr.site_from_crawl("crawl-1")["id"] == "site-1"
    assert route.called


@respx.mock
def test_search_sends_the_api_fields(client: Kloakd) -> None:
    route = respx.post(f"{BASE}/skanyr/search").mock(return_value=mock_response({"results": []}))
    client.skanyr.search("pricing", site_id="site-1", limit=5)
    assert json.loads(route.calls.last.request.content) == {"query": "pricing", "site_id": "site-1", "limit": 5}


@respx.mock
def test_search_one_site_with_q(client: Kloakd) -> None:
    route = respx.get(f"{BASE}/skanyr/sites/site-1/search").mock(return_value=mock_response({"results": []}))
    client.skanyr.search_site("site-1", "api docs", limit=3)
    params = route.calls.last.request.url.params
    assert (params["q"], params["limit"]) == ("api docs", "3")


@respx.mock
def test_sync(client: Kloakd) -> None:
    route = respx.post(f"{BASE}/skanyr/sync").mock(return_value=mock_response({"fetched": 2}))
    client.skanyr.sync("site-1", urls=["https://example.com/a"], policy="changed")
    assert json.loads(route.calls.last.request.content) == {"site_id": "site-1", "urls": ["https://example.com/a"], "policy": "changed"}
