# kloakd-sdk — Official Python SDK for KLOAKD

[![PyPI](https://img.shields.io/pypi/v/kloakd-sdk)](https://pypi.org/project/kloakd-sdk/)
[![Python](https://img.shields.io/pypi/pyversions/kloakd-sdk)](https://pypi.org/project/kloakd-sdk/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

The KLOAKD SDK gives Python developers typed access to the KLOAKD API through seven namespaces: `evadr`, `webgrph`, `skanyr`, `nexus`, `parlyr`, `fetchyr` and `kolektr`. A call's artifact id can be passed to a later call, so a page fetched once is not fetched again.

## Installation

```bash
pip install kloakd-sdk
```

Requires Python 3.9+ and `httpx>=0.27` (installed automatically).

## Quickstart

```python
from kloakd import Kloakd

client = Kloakd(
    api_key="sk-live-...",
    organization_id="your-org-id",
)

# Step 1: Fetch with anti-bot bypass
fetch = client.evadr.fetch("https://books.toscrape.com")
print(f"Fetched via tier {fetch.tier_used}")

# Step 2: Crawl the site hierarchy (waits until the crawl ends or is held)
crawl = client.webgrph.crawl("https://books.toscrape.com", max_depth=2)
print(f"Found {crawl.total_pages} pages")

# Step 3: Extract structured data — reuse the Evadr artifact again
data = client.kolektr.page(
    "https://books.toscrape.com",
    schema={"title": "css:h3 a", "price": "css:p.price_color"},
    item_selector="article.product_pod",   # one record per book
    fetch_artifact_id=fetch.artifact_id,
)
for book in data.records[:3]:
    print(book)
```

## The seven namespaces

| Namespace | Module | Purpose |
|---|---|---|
| `client.evadr` | Evadr | Fetch a page, analyse a site's protection, fetch jobs, proxies |
| `client.webgrph` | Webgrph | Crawl a site and list its pages; crawl, extract and download in one job |
| `client.skanyr` | Skanyr | Site knowledge store: sites, resources, search, history |
| `client.nexus` | Nexus | Analyse a page, synthesise and verify an extraction strategy (`analyze`, `synthesize`, `verify`, `reason`) |
| `client.parlyr` | Parlyr | Conversational NLP → extraction intent |
| `client.fetchyr` | Fetchyr | Authentication, login sessions, MFA, forms, workflows |
| `client.kolektr` | Kolektr | Structured data extraction |

## Artifact Chaining

Artifacts are the composition primitive — the output of one module becomes the input to another:

```
evadr.fetch()    → artifact_id (FETCHED_CONTENT)
  └─→ kolektr.page(fetch_artifact_id=...)       # skip re-fetch

fetchyr.authenticate() → artifact_id (AUTHENTICATED_SESSION)
  └─→ evadr.fetch(session_artifact_id=...)      # authenticated fetch
  └─→ webgrph.crawl(session_artifact_id=...)    # authenticated crawl
  └─→ kolektr.page(session_artifact_id=...)

webgrph.crawl()  → crawl_id (SITE_HIERARCHY)
  └─→ skanyr.site_from_crawl(crawl_id)          # into the site store
```

## Async Client

```python
from kloakd import AsyncKloakd

client = AsyncKloakd(api_key="sk-live-...", organization_id="your-org-id")

async def main():
    fetch = await client.evadr.fetch("https://books.toscrape.com")
    data  = await client.kolektr.page("https://books.toscrape.com",
                                       fetch_artifact_id=fetch.artifact_id)

    # SSE stream: pipeline events (type is pipeline_step, pipeline_error
    # or pipeline_complete)
    async for event in client.webgrph.crawl_stream("https://books.toscrape.com"):
        print(event.type, event.stage_id, event.message, event.progress_pct)
```

The sync and async clients have the same methods with the same arguments.

## Error Handling

```python
from kloakd.errors import KloakdError, RateLimitError, AuthenticationError
import time

try:
    result = client.evadr.fetch("https://example.com")
except RateLimitError as e:
    time.sleep(e.retry_after)
except AuthenticationError:
    # Rotate API key
    raise
except KloakdError as e:
    print(f"Error {e.status_code}: {e.message}")
```

**Error types:**

| Class | HTTP | Cause |
|---|---|---|
| `AuthenticationError` | 401 | Invalid or expired API key |
| `PaymentRequiredError` | 402 | The plan's last payment failed |
| `NotEntitledError` | 403 | Plan doesn't include this module (`not_entitled`: `module`) or feature (`tier_access_denied`: `feature`, `current_tier`, `required_tier`). A subclass of `ForbiddenError` |
| `ForbiddenError` | 403 | Any other 403: the key may not access this resource |
| `ConcurrencyLimitError` | 409 | Every work slot of the organisation is in use (`concurrent_limit`, `active_crawls`, `active_requests`, `tier`); not retried. See *Work slots* |
| `QuotaExceededError` | 429 | GB allocation and top-ups used up (`gb_exhausted`; not retried) |
| `RateLimitError` | 429 | Request rate exceeded (`retry_after`, `reset_at`; retried). With `quota_exhausted` true it is the playground quota (`quota_used`, `quota_limit`, `upgrade_url`), which does not reset and is not retried |
| `UpstreamError` | 502 | Target site unreachable |
| `BillingUnavailableError` | 503 | Usage could not be checked; retried after `retry_after` |
| `JobFailedError` / `JobTimeoutError` | — | A handed-off request, fetch job or crawl failed (or expired), or was still running when the wait ran out (`job_id`) |
| `ApiError` | 4xx/5xx | Any other API error (a 422 keeps the validation messages). `code` holds the API's error code, for example 409 `invalid_batch_transition` and 503 `dispatch_failed` on the batch calls |

Every error has `message`, `status_code` and `code` (the API's error code,
such as `rate_limited`, or None). A response that is not JSON (a proxy's
error page) does not crash the client: its text becomes the message.

**Retries:** 429 `rate_limited` and 503 `billing_unavailable` are retried on
any method, after `Retry-After` (or until `reset_at`). Other 5xx answers and
network errors are retried only for GET, HEAD and DELETE: a POST, PUT or
PATCH may already have done its work, so it is never sent twice. At most
`max_retries` attempts (default 3); `timeout` (default 100 s) applies to
each attempt.

**Long requests:** the API answers within about 85 seconds (it sits behind
Cloudflare, which closes requests at 100 s). A request still running then
continues as a job: the API answers HTTP 202 with a `poll_url`. The SDK
follows it and returns the same typed result as a direct answer. This
applies to `evadr.fetch`, `kolektr.page` / `page_all`,
`fetchyr.authenticate`, `detect_forms`, `fill_form`, `detect_mfa`,
`nexus.analyze` and `synthesize` and `client.unified_scrape`. The first poll is after
`poll_interval` seconds (default 3), each later wait half as long again up
to 15 s, for at most `poll_timeout` seconds (default 900); set both on the
client (`Kloakd(..., poll_interval=, poll_timeout=)`), or per call on
`evadr.fetch` and `client.unified_scrape`. A failed job, or one whose result has expired (an hour after
it ends), raises `JobFailedError`; one still running at the timeout raises
`JobTimeoutError` with its `job_id`. Resume it with
`client.wait_for_handoff(e.job_id)` (or read its state once with
`client.get_handoff(job_id)`); a fetch job resumes with
`client.evadr.wait_for_job(e.job_id)`. The default `timeout` of 100 s is
above the API's 85 s wait, so the client receives the 202 rather than
timing out first.

**Work slots:** every metered call (a fetch, an extraction, a crawl start,
...) holds one of the organisation's work slots while it runs; crawls and
batches hold theirs until they end. Free runs 10 at once, Starter 5, Pro 10,
Pro+ 20, Developer 50, Enterprise 100 (the anonymous test keys of the docs
run 2). A call over the limit is queued by the API: one that can continue
as a job (the calls listed under *Long requests*) waits for a slot as a
job; any other waits up to 10 seconds and is then answered 409
`concurrent_limit`, which the SDK raises as `ConcurrencyLimitError`. It is
not retried, so wait for one of your calls to finish and try again:

```python
from kloakd import ConcurrencyLimitError

try:
    client.kolektr.page(url, schema={"title": "css:h1"})
except ConcurrencyLimitError as e:
    print(e.tier, e.concurrent_limit, e.active_crawls, e.active_requests)
```

## Crawls and pages

A crawl maps the site's pages and links; crawl-extract also returns the
items on each page as rows.

### Estimate, then start

Before a crawl or crawl-extract, ask what it would do. The estimate is not
metered (no charge, no work slot):

```python
est = client.webgrph.estimate_crawl("https://example.com", max_depth=2, max_pages=50)
print(est.max_depth, est.max_pages, est.clamped)          # after the plan's limits
print(est.site.sitemap_pages, est.est_pages.low, est.est_pages.high, est.est_pages.source)
print(est.est_duration_s.low, est.est_duration_s.high, est.time_budget_s)
print(est.est_gb, est.gb_remaining, est.warning)
print(est.explanation)

# Start with the values the estimate settled on, or adjust and estimate again
crawl = client.webgrph.crawl("https://example.com", est.max_depth, est.max_pages)

# The same for crawl-extract (needs Kolektr); the duration includes extraction
est = client.webgrph.estimate_crawl_extract("https://example.com", max_pages=50,
                                            extract={"fields": ["title", "price"]})
```

`est_pages.source` is `sitemap`, `homepage_links` or `limit` (only the cap
is known, for example when the site probe failed). `will_hit_page_cap` is
True when the site seems larger than `max_pages`, and `will_exhaust_quota`
when the crawl may use up the data that remains.

A running crawl reports `time_budget_s`, `elapsed_s` and `est_remaining_s`
(`CrawlResult` and `CrawlExtractStatus`; None until the crawl reports them).

```python
crawl = client.webgrph.crawl("https://example.com")   # waits, then loads every page
if crawl.held:
    print(crawl.message)          # paused for quota; see "Held crawls"
elif not crawl.ok:
    print(crawl.status, crawl.error)
all_pages = crawl.pages
page = client.webgrph.get_crawl_pages(crawl.crawl_id, limit=100)   # one page, by cursor (limit 1-1000)
folders = client.webgrph.crawl_all_pages(crawl.crawl_id, include_grouping=True)
all_records = client.kolektr.page_all("https://example.com")

# Discover, fetch and extract in one call. A page that fails is marked
# failed; billing, plan, key and rate-limit errors are raised.
site = client.crawl("https://example.com", max_depth=2,
                    extract_schema={"title": "css:h1"})
print(site.success, site.error, site.pages_fetched, site.pages_failed)

# Store the crawl as a site, then search it
stored = client.skanyr.site_from_crawl(crawl.crawl_id)
hits = client.skanyr.search("pricing", site_id=stored["site_id"])
zip_bytes = client.skanyr.export_site(stored["site_id"])   # a ZIP archive
```

`max_depth` and `max_pages` are sent only when you give them; left out, the
API uses your plan's default (up to 0.6.0 the SDK sent 3 and 100).

Pages: only fetched pages are listed, each under the page the crawl found
it on, and `total_pages` / `max_depth_reached` count fetched pages only.
`include_grouping=True` also lists the tree's grouping folders, which were
never fetched (`PageNode.is_grouping`). `limit` is 1-1000 and a cursor is
the `next_cursor` string of the previous page; anything else raises
`ValueError` before the request (the API would answer 422). A node carries
`fetch_status` (`fetched`, `unfetched` or `not_requested`) and
`fetch_error` when the API sends them. It has no HTTP status code: the
`status_code` and `crawl_parent_url` attributes of 0.6.0 were always None
and are gone.

### Held crawls

When the organisation's quota runs out, a crawl is paused, not failed: its
status is `held_quota`. It keeps its id and resumes by itself when quota
returns (an upgrade, a top-up or a new billing period); a crawl held for 30
days ends `failed` with `error_code == "held_quota_expired"`.

`webgrph.crawl`, `webgrph.wait_for_crawl` and `client.crawl` return a held
crawl; they do not raise and do not poll it to the timeout:

```python
crawl = client.webgrph.crawl("https://example.com")
if crawl.held:                      # status == "held_quota"
    print(crawl.message)            # the API's text; crawl.error is None
    # later, with the same id:
    crawl = client.webgrph.wait_for_crawl(crawl.crawl_id, url="https://example.com")
```

A held crawl has `success` False, `error` None and no pages.
`webgrph.crawl_all` returns an empty list for it (as for a failed crawl),
and `webgrph.crawl_stream` ends. `client.crawl` reports it as
`site.held`, `site.crawl_status`, `site.crawl_id` and `site.message`.
`wait_for_crawl(crawl_id)` waits for any crawl by its id: one started with
`crawl(..., wait=False)`, a held one, or one you continued.

### Partial crawls and `continue_crawl`

A crawl that stopped before it fetched everything still ends `completed`.
The result says what it did:

```python
crawl = client.webgrph.crawl("https://example.com")
print(crawl.is_partial, crawl.partial_reason)
print(crawl.pages_discovered, crawl.pages_fetched, crawl.pages_unfetched)
if crawl.resumable:                 # it stopped at its time budget
    client.webgrph.continue_crawl(crawl.crawl_id)      # queued again, same id
    crawl = client.webgrph.wait_for_crawl(crawl.crawl_id)
```

`continue_crawl` puts the crawl back in the queue to fetch the pages it
left, with a new time budget; pages already fetched are not fetched again.
The API answers 409 (`ApiError`) for a crawl that did not stop at its time
budget (an unknown id included), has not ended, or is already being
continued. Each of these fields is None when the API did not send it.

Continue with more: give a higher `max_pages` (or `max_depth`), clamped to
your plan. A crawl that stopped at `max_pages` can then continue too. A
lower value raises `ApiError` 422 with `code == "continue_cannot_lower"`.
Without options no body is sent and the crawl continues as before. A
crawl-extract job continues the same way, and then extracts the new pages:

```python
client.webgrph.continue_crawl(crawl.crawl_id, max_pages=500)
client.webgrph.continue_crawl_extract(job.job_id, max_pages=500)
status = client.webgrph.wait_for_crawl_extract(job.job_id)
```

Extraction schemas are the shorthand `{"field": "css:selector"}` (the
`css:` prefix is optional; a value may also be
`{"selector": ..., "attribute": ..., "type": "list"}`), a list of fields
`[{"name": "link", "selector": "a", "attribute": "href"}]`, or a full
`schema_spec` with `fields`.

### One record per item: `item_selector`

On a list page, `item_selector` (CSS) makes one record per element it
matches, and each field's selector is read inside that element: the first
match gives the value (every match for `type: "list"`), its text or the
named `attribute`; a field with no match in an item is `None`; a field
without a selector reads the item element itself. Without `item_selector`
the result is as before: one record for the page.

```python
books = client.kolektr.page(
    "https://books.toscrape.com",
    schema={
        "title": {"selector": "h3 a", "attribute": "title"},
        "price": "css:p.price_color",
        "url": {"selector": "h3 a", "attribute": "href"},
    },
    item_selector="article.product_pod",
)
print(books.total_records)          # one record per book on the page
print(books.records[0]["title"])

# The same on HTML you already have, and as a full spec for client.crawl()
client.kolektr.extract_html(html, url, schema={"name": "td.name"}, item_selector="tr")
from kloakd import schema_spec
spec = schema_spec({"title": "h3 a"}, item_selector="article.product_pod")
site = client.crawl("https://books.toscrape.com", extract_schema=spec)
```

An empty `item_selector`, or one without fields, raises `ValueError`; an
invalid CSS selector is refused by the API with 422 (`ApiError`).

## Crawl, extract and download

One job crawls a site, extracts every page and keeps the rows for download
(new in 0.7.0). The plan must include Kolektr, and a test key is refused
(403).

```python
job = client.webgrph.start_crawl_extract(
    "https://example.com", max_depth=2, max_pages=200,
    extract={"schema": {"item_selector": "li.product",
                        "fields": [{"name": "title", "selector": "h3"}]}},
)
status = client.webgrph.wait_for_crawl_extract(job.job_id)   # polls to the end
print(status.status, status.pages_extracted, status.items, status.shapes)

# or start and wait in one call (raises JobFailedError when the job fails)
status = client.webgrph.crawl_extract("https://example.com", max_pages=200)

# Rows, a page at a time (limit 1-1000) or all of them
page = client.webgrph.get_crawl_extract_results(job.job_id, limit=500, kind="item")
for row in client.webgrph.iter_crawl_extract_results(job.job_id):
    print(row.page_url, row.data)

# The crawled pages and how each was extracted
failed = client.webgrph.get_crawl_extract_pages(job.job_id, status="failed")

# Download: json, ndjson or csv, streamed to a file ...
saved = client.webgrph.download_crawl_extract(job.job_id, "rows.csv", format="csv")
print(saved.path, saved.bytes, saved.job_status, saved.crawl)
# ... or as a stream
with client.webgrph.export_crawl_extract(job.job_id, format="ndjson") as export:
    for chunk in export.iter_bytes():
        ...

client.webgrph.cancel_crawl_extract(job.job_id)   # 409 (ApiError) once it has ended
```

`extract` is the API's own object: `entity_type`, `fields` (a list of
names) or `schema` (`item_selector` and `fields` of `{name, selector,
attribute, type}`); without it the API chooses what to extract.
`wait_for_crawl_extract` polls every `poll_interval` seconds (default 3) for
at most `poll_timeout` (default 3600) and raises `JobTimeoutError` while the
job still runs; a cancelled job is returned, not raised. A job whose crawl
is held for quota is returned at once too, with `status.held` True and
`status.finished` False (see *Held crawls*); wait for it again later.
`status.crawl` says what the job's crawl did (`status`, `is_partial`,
`partial_reason`, `pages_discovered`, `pages_fetched`, `pages_unfetched`,
`cancelled`, `root_unfetched`, `error`, `error_code`); it is None until the
API sends it. The CSV starts with a UTF-8 byte order mark. A refused
download leaves no file.

### What an export says about its job

An export (`export_crawl_extract`) and a saved file
(`download_crawl_extract`) carry two things read from the response headers:

- `job_status` (`X-Job-Status`): the job's status when the export began. A
  value other than `completed` means the file holds the rows stored so far.
- `crawl` (the `X-Crawl-*` headers): `status`, `is_partial`,
  `partial_reason`, `pages_discovered`, `pages_fetched`, `pages_unfetched`,
  `cancelled`, `root_unfetched`. A value whose header was not sent is None;
  `crawl` itself is None when the response has no `X-Crawl-*` header.

```python
with client.webgrph.export_crawl_extract(job.job_id, format="csv") as export:
    if export.crawl and export.crawl.is_partial:
        print("partial crawl:", export.crawl.partial_reason,
              export.crawl.pages_unfetched, "pages not fetched")
```

A batch job's results download the same way:

```python
client.download_batch_job(batch_job_id, "batch.ndjson", format="ndjson")
with client.export_batch_job(batch_job_id, format="csv") as export:
    data = export.read()
```

A batch export sends neither header: its `job_status` and `crawl` are None.

The async client has the same methods: `await` the calls, `async for` over
`iter_crawl_extract_results`, and
`async with await client.webgrph.export_crawl_extract(job_id) as export:`
with `export.aiter_bytes()`.

## Batch jobs

A batch extracts a list of URLs, one item per URL, and holds one work slot
until it ends. It needs a live key (a test key is refused with 403).

```python
batch = client.create_batch_job(
    ["https://shop.example/p/1", "https://shop.example/p/2"],
    entity_type="products",
    fields=["name", "price"],
)

client.pause_batch_job(batch.id)    # items already running finish; the rest wait
client.resume_batch_job(batch.id)   # the waiting items are queued again, each once
state = client.get_batch_job(batch.id)  # status, total_items, completed_items, message

page = client.get_batch_job_results(batch.id, limit=100)
for item in page.results:
    print(item.job_id, item.status, item.extracted_data)

client.cancel_batch_job(batch.id)   # items not yet ended are cancelled; finished ones keep their results
```

- `status` is `pending`, `running`, `paused`, `held_quota`, `completed`,
  `failed` or `cancelled`. Only a running batch can be paused, only a
  paused one resumed, and a batch that has completed or failed cannot be
  cancelled: the API answers 409 and the SDK raises an `ApiError` with
  `code` `invalid_batch_transition` (the message names the batch's status).
- Repeating a call is not an error: pausing a paused batch, resuming a
  running one and cancelling a cancelled one answer the batch as it is.
- `resume_batch_job` can raise a 503 `ApiError` with `code`
  `dispatch_failed`: the items could not be queued and the batch is paused
  again, so call it again. `create_batch_job` raises the same when the
  batch could not be queued; nothing was started. Neither is retried by
  the SDK.
- Creating or resuming over the plan's running batches raises
  `ConcurrencyLimitError`; more URLs than the plan's limit is a 413
  `ApiError` with `code` `batch_too_large`.
- `client.list_batch_jobs(page=1, page_size=20)` lists the organisation's
  batches, newest first. `export_batch_job` and `download_batch_job`
  (above) give the rows as a file.

## Unified scrape

`client.unified_scrape(url, ...)` lets the API choose how to scrape a URL:
level 1 (direct extraction) or level 2 (the Strategy Engine), escalating
when the first fails. It needs a live key whose plan has Kolektr and Nexus
(`ForbiddenError` with `code` `test_key_not_allowed` or
`module_not_entitled` otherwise).

```python
scrape = client.unified_scrape(
    "https://shop.example/list",
    prompt="product names and prices",
    mode="auto",  # or "level1", "level2"
    schema={"name": "product name", "price": "price"},
)
if scrape.auth_required:
    # The URL is behind a login: nothing was scraped.
    # scrape.discovery_id names the auth-chain discovery.
    ...
elif scrape.status == "failed":
    # The scrape failed. success is still True and there is no error text;
    # job_id names no stored job (get_unified_scrape would raise ApiError 404).
    ...
else:
    job = client.get_unified_scrape(scrape.job_id)  # status, level, progress, result, escalation_path
```

Check `status`: when the scrape fails the API still answers with `success`
true and `status` `"failed"`, without the error text, and that answer's
`job_id` names no stored job, so `get_unified_scrape` on it raises
`ApiError` 404.

Arguments: `prompt`, `mode`, `schema`, `options`, `context`, `constraints`,
`session_artifact_id` (a login session), and `poll_interval` /
`poll_timeout` for a request the API hands off (202), which is followed
like every other long request.

The async client has the same batch and unified scrape methods.

## Parlyr — chat

```python
turn = client.parlyr.chat("my-session", "Get book titles from https://books.toscrape.com")
print(turn.response)          # text and clarification content
print(turn.interpretation)    # the plan: url, entity, fields, summary, ...
print(turn.results)           # data of each results event
if not turn.ok:
    print([e.content for e in turn.errors])

for event in client.parlyr.chat_stream("my-session", "Also get prices"):
    print(event.type, event.content, event.data, event.actions)
```

## Fetchyr — RPA & Authentication

```python
# Store credentials once, then log in and produce a reusable session
client.fetchyr.store_credentials("app", username="user@example.com", password="secret")
session = client.fetchyr.authenticate("app", "https://app.example.com/login")

# Detect and handle MFA
mfa = client.fetchyr.detect_mfa("https://app.example.com/mfa",
                                  session_artifact_id=session.artifact_id)
if mfa.mfa_detected:
    challenge = client.fetchyr.submit_mfa(mfa.challenge_id, "123456")

# Detect forms, run workflows, deduplicate records
forms  = client.fetchyr.detect_forms("https://example.com/signup")
seen   = client.fetchyr.check_duplicate("https://example.com/item/1")
```

### Login sessions: your own account

When a fetch, crawl or extraction answers `auth_required`, make a session
from your own account and pass its id as `session_artifact_id`.

```python
# From the cookies of a session in your own browser. cookies and user_agent
# (that browser's navigator.userAgent) are both required for this method.
login = client.fetchyr.start_login_session(
    "https://acme.example/account",
    method="cookies",
    cookies=[{"name": "sid", "value": "...", "domain": "acme.example"}],
    user_agent="Mozilla/5.0 ...",
)
print(login.status, login.cookies_kept, login.cookies_dropped)   # "ready"
page = client.evadr.fetch("https://acme.example/account",
                          session_artifact_id=login.session_artifact_id)

# Or let the API open the site's login (the default method, "interactive")
login = client.fetchyr.start_login_session("https://acme.example/account")
print(login.status, login.discovery_id)        # "waiting_for_login"
state = client.fetchyr.get_auth_chain_status(login.discovery_id)

# A session's status, and lifting a pause
status = client.fetchyr.get_session(login.session_artifact_id)
print(status.status, status.pause_reason, status.requests_this_hour)
if status.status == "paused" and status.pause_reason != "logged_out":
    status = client.fetchyr.resume_session(status.artifact_id)
```

Only the arguments you give are sent. The API answers 422 (`ApiError`) for
method `"cookies"` without cookies or without a user agent, or when none of
the cookies is the site's. `get_session` returns no cookie value.
`resume_session` raises `ApiError` (409) when the session is not paused or
was paused because the site signed it out; log in again then.

## Links

- **Documentation:** https://docs.kloakd.dev/sdk/python
- **API Reference:** https://docs.kloakd.dev/api
- **Dashboard:** https://app.kloakd.dev
- **GitHub:** https://github.com/kloakd-dev/kloakd-sdk-python
- **PyPI:** https://pypi.org/project/kloakd-sdk/

## License

MIT
