# kloakd-sdk — Official Python SDK for KLOAKD

[![PyPI](https://img.shields.io/pypi/v/kloakd-sdk)](https://pypi.org/project/kloakd-sdk/)
[![Python](https://img.shields.io/pypi/pyversions/kloakd-sdk)](https://pypi.org/project/kloakd-sdk/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

The KLOAKD SDK gives Python developers typed access to all 7 KLOAKD modules. Modules compose like Unix pipes — the artifact output of one becomes the input to the next, eliminating redundant fetches.

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

# Step 2: Crawl the site hierarchy (waits until the crawl finishes)
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

## The 7 Modules

| Namespace | Module | Purpose |
|---|---|---|
| `client.evadr` | Evadr | Anti-bot bypass (5-tier escalation) |
| `client.webgrph` | Webgrph | Site mapping & BFS crawl |
| `client.skanyr` | Skanyr | Site knowledge store: sites, resources, search, history |
| `client.nexus` | Nexus | 5-layer strategy engine |
| `client.parlyr` | Parlyr | Conversational NLP → extraction intent |
| `client.fetchyr` | Fetchyr | RPA, authentication, MFA, workflows |
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
| `ApiError` | 4xx/5xx | Any other API error (a 422 keeps the validation messages) |

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
`fetchyr.authenticate`, `detect_forms`, `fill_form`, `detect_mfa` and
`nexus.analyze` and `synthesize`. The first poll is after
`poll_interval` seconds (default 3), each later wait half as long again up
to 15 s, for at most `poll_timeout` seconds (default 900); set both on the
client (`Kloakd(..., poll_interval=, poll_timeout=)`), or per call on
`evadr.fetch`. A failed job, or one whose result has expired (an hour after
it ends), raises `JobFailedError`; one still running at the timeout raises
`JobTimeoutError` with its `job_id`. Resume it with
`client.wait_for_handoff(e.job_id)` (or read its state once with
`client.get_handoff(job_id)`); a fetch job resumes with
`client.evadr.wait_for_job(e.job_id)`. The default `timeout` of 100 s is
above the API's 85 s wait, so the client receives the 202 rather than
timing out first.

**Work slots:** every metered call (a fetch, an extraction, a crawl start,
...) holds one of the organisation's work slots while it runs; crawls and
batches hold theirs until they end. Free runs 2 at once, Starter 5, Pro 10,
Pro+ 20, Developer 50, Enterprise 100. Over the limit the API answers 409
`concurrent_limit` and the SDK raises `ConcurrencyLimitError`; it is not
retried, so wait for one of your calls to finish and try again:

```python
from kloakd import ConcurrencyLimitError

try:
    client.kolektr.page(url, schema={"title": "css:h1"})
except ConcurrencyLimitError as e:
    print(e.tier, e.concurrent_limit, e.active_crawls, e.active_requests)
```

## Crawls and pages

```python
crawl = client.webgrph.crawl("https://example.com")   # waits, then loads every page
if not crawl.ok:
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

Pages: only fetched pages are listed, each under the page the crawl found
it on, and `total_pages` / `max_depth_reached` count fetched pages only.
`include_grouping=True` also lists the tree's grouping folders, which were
never fetched (`PageNode.is_grouping`). `limit` is 1-1000 and a cursor is
the `next_cursor` string of the previous page; anything else raises
`ValueError` before the request (the API would answer 422).

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
(unreleased; after 0.6.0). The plan must include Kolektr, and a test key is
refused (403).

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
print(saved.path, saved.bytes, saved.job_status)
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
job still runs; a cancelled job is returned, not raised. An export of a job
that has not completed holds the rows stored so far (`job_status`). The CSV
starts with a UTF-8 byte order mark. A refused download leaves no file.

A batch job's results download the same way:

```python
client.download_batch_job(batch_job_id, "batch.ndjson", format="ndjson")
with client.export_batch_job(batch_job_id, format="csv") as export:
    data = export.read()
```

The async client has the same methods: `await` the calls, `async for` over
`iter_crawl_extract_results`, and
`async with await client.webgrph.export_crawl_extract(job_id) as export:`
with `export.aiter_bytes()`.

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

## Links

- **Documentation:** https://docs.kloakd.dev/sdk/python
- **API Reference:** https://docs.kloakd.dev/api
- **Dashboard:** https://app.kloakd.dev
- **GitHub:** https://github.com/kloakd-dev/kloakd-sdk-python
- **PyPI:** https://pypi.org/project/kloakd-sdk/

## License

MIT
