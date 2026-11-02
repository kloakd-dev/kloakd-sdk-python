"""The 0.6.0 changes, each against the shape kobe-scraper's code sends or reads.

Backend references are paths under kobe-scraper src/kobe_scraper/ (main at
1c74de2b, deployed 0bb0c6b5 on 2 November 2026).
"""

from __future__ import annotations

import json
from typing import Any, List

import pytest
import respx

import kloakd
import kloakd._http as http_mod
from kloakd import AsyncKloakd, ConcurrencyLimitError, Kloakd, PageNode, schema_spec
from kloakd._http import raise_for_status
from tests.conftest import ORG_PREFIX, TEST_BASE_URL, TEST_ORG_ID, mock_response

BASE = f"{TEST_BASE_URL}{ORG_PREFIX}"

EXTRACTED = {
    "success": True,
    "url": "https://books.toscrape.com",
    "method": "level1",
    "records": [{"title": "A", "price": "1"}, {"title": "B", "price": "2"}],
    "total_records": 2,
}


@pytest.fixture
def client() -> Kloakd:
    return Kloakd(api_key="sk-test-k", organization_id=TEST_ORG_ID, base_url=TEST_BASE_URL)


@pytest.fixture
def aclient() -> AsyncKloakd:
    return AsyncKloakd(api_key="sk-test-k", organization_id=TEST_ORG_ID, base_url=TEST_BASE_URL)


def _body(route: Any, i: int = -1) -> Any:
    return json.loads(route.calls[i].request.content)


# ── 1. Kolektr item_selector (GAP-API-11, modules/kolektr/router.py SchemaSpec) ──


@respx.mock
def test_shorthand_schema_carries_item_selector(client: Kloakd) -> None:
    route = respx.post(f"{BASE}/kolektr/extract").mock(return_value=mock_response(EXTRACTED))
    result = client.kolektr.page(
        "https://books.toscrape.com",
        schema={
            "title": {"selector": "css:h3 a", "attribute": "title"},
            "price": "css:p.price_color",
            "tags": {"selector": "li", "type": "list"},
            "id": {"attribute": "data-id"},
        },
        item_selector="article.product_pod",
    )
    assert _body(route)["schema_spec"] == {
        "item_selector": "article.product_pod",
        "fields": [
            {"name": "title", "selector": "h3 a", "attribute": "title"},
            {"name": "price", "selector": "p.price_color"},
            {"name": "tags", "selector": "li", "type": "list"},
            {"name": "id", "attribute": "data-id"},
        ],
    }
    assert result.total_records == 2 and len(result.records) == 2


@respx.mock
def test_extract_html_and_page_all_carry_item_selector(client: Kloakd) -> None:
    html_route = respx.post(f"{BASE}/kolektr/extract/html").mock(
        return_value=mock_response(EXTRACTED)
    )
    client.kolektr.extract_html(
        "<article></article>", "https://x.test", schema=[{"name": "t", "selector": "h3"}],
        item_selector="article",
    )
    assert _body(html_route)["schema_spec"] == {
        "fields": [{"name": "t", "selector": "h3"}], "item_selector": "article",
    }
    page_route = respx.post(f"{BASE}/kolektr/extract").mock(return_value=mock_response(EXTRACTED))
    records = client.kolektr.page_all(
        "https://x.test", schema={"t": "h3"}, item_selector=" article "
    )
    assert _body(page_route)["schema_spec"]["item_selector"] == "article"
    assert records == EXTRACTED["records"]


@respx.mock
def test_full_spec_with_item_selector_is_sent_as_given(client: Kloakd) -> None:
    route = respx.post(f"{BASE}/kolektr/extract").mock(return_value=mock_response(EXTRACTED))
    spec = {"item_selector": "li.row", "fields": [{"name": "t", "selector": "a"}], "max_pages": 2}
    client.kolektr.page("https://x.test", schema=spec)
    assert _body(route)["schema_spec"] == spec


@respx.mock
def test_without_item_selector_the_body_is_unchanged_from_050(client: Kloakd) -> None:
    route = respx.post(f"{BASE}/kolektr/extract").mock(return_value=mock_response(EXTRACTED))
    client.kolektr.page("https://x.test", schema={"title": "css:h3 a"})
    assert _body(route)["schema_spec"] == {"fields": [{"name": "title", "selector": "h3 a"}]}


@pytest.mark.parametrize(
    "schema,item_selector",
    [
        ({"t": "h3"}, "   "),  # empty -> API 422
        ({"fields": [], "item_selector": "li"}, None),  # no fields -> API 422
        ({"fields": [{"name": "t"}], "item_selector": "li"}, "ul"),  # conflicting
    ],
)
def test_item_selector_errors_are_raised_before_the_request(
    schema: Any, item_selector: Any
) -> None:
    with pytest.raises(ValueError):
        schema_spec(schema, item_selector)


def test_item_selector_without_a_schema_is_refused(client: Kloakd) -> None:
    with pytest.raises(ValueError, match="needs a schema"):
        client.kolektr.page("https://x.test", item_selector="article")


@respx.mock
async def test_async_page_and_extract_html_carry_item_selector(aclient: AsyncKloakd) -> None:
    route = respx.post(f"{BASE}/kolektr/extract").mock(return_value=mock_response(EXTRACTED))
    await aclient.kolektr.page("https://x.test", schema={"t": "h3"}, item_selector="article")
    assert _body(route)["schema_spec"]["item_selector"] == "article"
    html_route = respx.post(f"{BASE}/kolektr/extract/html").mock(
        return_value=mock_response(EXTRACTED)
    )
    await aclient.kolektr.extract_html("<p/>", "https://x.test", {"t": "h3"}, item_selector="p")
    assert _body(html_route)["schema_spec"]["item_selector"] == "p"
    await aclient.kolektr.page_all("https://x.test", schema={"t": "h3"}, item_selector="li")
    assert _body(route)["schema_spec"]["item_selector"] == "li"


def test_schema_spec_and_types_are_exported() -> None:
    assert kloakd.schema_spec is schema_spec
    assert {"SchemaSpec", "SchemaField", "schema_spec"} <= set(kloakd.__all__)
    assert schema_spec({"t": "css:h3"}, "article") == {
        "fields": [{"name": "t", "selector": "h3"}], "item_selector": "article",
    }


# ── 2. Crawl pages: limit, cursor, include_grouping (GAP-API-9/10, webgrph/router.py) ──


NODE = {
    "id": "1", "url": "https://s.test/a", "parent_url": "https://s.test/", "children_urls": [],
    "depth": 1, "category": "page", "classification_confidence": 0.0,
    "metadata": {"title": "A", "is_grouping": False},
}
GROUP = {
    **NODE, "id": "g", "url": "https://s.test/#path-catalogue",
    "metadata": {"title": "catalogue", "is_grouping": True},
}


@respx.mock
def test_pages_default_omits_include_grouping(client: Kloakd) -> None:
    route = respx.get(f"{BASE}/webgrph/crawl/c1/pages").mock(
        return_value=mock_response({"crawl_id": "c1", "nodes": [NODE], "next_cursor": None, "total": 1})
    )
    client.webgrph.get_crawl_pages("c1")
    params = route.calls.last.request.url.params
    assert params["limit"] == "500" and "include_grouping" not in params


@respx.mock
def test_pages_include_grouping_and_node_metadata(client: Kloakd) -> None:
    route = respx.get(f"{BASE}/webgrph/crawl/c1/pages").mock(
        side_effect=[
            mock_response({"crawl_id": "c1", "nodes": [GROUP], "next_cursor": "1", "total": 2}),
            mock_response({"crawl_id": "c1", "nodes": [NODE], "next_cursor": None, "total": 2}),
        ]
    )
    nodes = client.webgrph.crawl_all_pages("c1", include_grouping=True, limit=1)
    assert [c.request.url.params["include_grouping"] for c in route.calls] == ["true", "true"]
    assert [c.request.url.params["limit"] for c in route.calls] == ["1", "1"]
    assert route.calls[1].request.url.params["cursor"] == "1"
    assert [n.is_grouping for n in nodes] == [True, False]
    assert nodes[1].parent_url == "https://s.test/"
    assert nodes[1].crawl_parent_url is None  # the listing does not send it


def test_stored_page_dicts_carry_crawl_parent_url() -> None:
    # modules/webgrph/module.py serialize_page: flat is_grouping / crawl_parent_url
    from kloakd.modules.webgrph import _node

    node = _node({
        "url": "https://s.test/b", "depth": 2, "title": "B",
        "parent_url": "https://s.test/#path-catalogue",
        "crawl_parent_url": "https://s.test/a", "is_grouping": False,
    })
    assert node == PageNode(
        url="https://s.test/b", depth=2, title="B", parent_url="https://s.test/#path-catalogue",
        crawl_parent_url="https://s.test/a", is_grouping=False,
    )


@pytest.mark.parametrize("limit", [0, 1001, -1, True, 2.5])
def test_pages_limit_outside_1_to_1000_is_refused(client: Kloakd, limit: Any) -> None:
    with pytest.raises(ValueError, match="limit"):
        client.webgrph.get_crawl_pages("c1", limit=limit)


@pytest.mark.parametrize("cursor", ["-1", "abc", "1.5", ""])
def test_pages_bad_cursor_is_refused(client: Kloakd, cursor: str) -> None:
    with pytest.raises(ValueError, match="cursor"):
        client.webgrph.get_crawl_pages("c1", cursor=cursor)


@respx.mock
async def test_async_pages_include_grouping(aclient: AsyncKloakd) -> None:
    route = respx.get(f"{BASE}/webgrph/crawl/c1/pages").mock(
        return_value=mock_response({"crawl_id": "c1", "nodes": [GROUP], "next_cursor": None, "total": 1})
    )
    nodes = await aclient.webgrph.crawl_all_pages("c1", include_grouping=True, limit=1000)
    assert route.calls.last.request.url.params["include_grouping"] == "true"
    assert route.calls.last.request.url.params["limit"] == "1000"
    assert nodes[0].is_grouping is True
    with pytest.raises(ValueError):
        await aclient.webgrph.get_crawl_pages("c1", limit=0)


# ── 3. Work slots: 409 concurrent_limit (GAP-BILL-13, kernel/gateway/dependencies.py) ──

WORK_SLOT_409 = {
    "detail": {
        "error": "concurrent_limit",
        "message": "Your free plan runs 2 jobs at once and all 2 are in use "
        "(1 crawl(s) or batch(es), 1 other request(s)). Try again when one finishes.",
        "tier": "free",
        "concurrent_limit": 2,
        "active_crawls": 1,
        "active_requests": 1,
    }
}


def test_409_work_slot_exposes_active_requests() -> None:
    with pytest.raises(ConcurrencyLimitError) as e:
        raise_for_status(409, b"", WORK_SLOT_409)
    err = e.value
    assert (err.tier, err.concurrent_limit, err.active_crawls, err.active_requests) == (
        "free", 2, 1, 1,
    )
    assert err.code == "concurrent_limit" and err.status_code == 409
    assert err.message.startswith("Your free plan runs 2 jobs")
    assert "active_requests=1" in repr(err)


def test_test_key_409_has_no_active_requests() -> None:
    body = {"detail": {"error": "concurrent_limit", "message": "Concurrent job limit reached (10).",
                       "test_key_id": "t", "concurrent_limit": 10}}
    with pytest.raises(ConcurrencyLimitError) as e:
        raise_for_status(409, b"", body)
    assert e.value.active_requests is None and e.value.concurrent_limit == 10


@respx.mock
def test_409_is_not_retried(client: Kloakd, monkeypatch: pytest.MonkeyPatch) -> None:
    waits: List[float] = []
    monkeypatch.setattr(http_mod.time, "sleep", waits.append)
    get = respx.get(f"{BASE}/webgrph/crawl/c1").mock(
        return_value=mock_response(WORK_SLOT_409, status_code=409)
    )
    post = respx.post(f"{BASE}/kolektr/extract").mock(
        return_value=mock_response(WORK_SLOT_409, status_code=409)
    )
    with pytest.raises(ConcurrencyLimitError):
        client.webgrph.get_crawl_status("c1")
    with pytest.raises(ConcurrencyLimitError) as e:
        client.kolektr.page("https://x.test", schema={"t": "h3"})
    assert get.call_count == 1 and post.call_count == 1 and waits == []
    assert e.value.active_requests == 1


# ── Version ──────────────────────────────────────────────────────────────────


@respx.mock
def test_user_agent_is_060(client: Kloakd) -> None:
    route = respx.get(f"{BASE}/skanyr/sites").mock(return_value=mock_response([]))  # type: ignore[arg-type]
    client.skanyr.list_sites()
    assert route.calls.last.request.headers["user-agent"] == "kloakd-sdk-python/0.6.0"
    assert kloakd.__version__ == "0.6.0"
