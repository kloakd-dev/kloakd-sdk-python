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
| `ConcurrencyLimitError` | 409 | Too many crawls or jobs running at once (`concurrent_limit`, `active_crawls`, `tier`) |
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
`nexus.analyze`, `synthesize` and `execute`. The first poll is after
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

**Nexus knowledge:** `nexus.execute(...)` returns `execution_result_id`;
pass it to `nexus.knowledge(result.execution_result_id)`.

## Crawls and pages

```python
crawl = client.webgrph.crawl("https://example.com")   # waits, then loads every page
if not crawl.ok:
    print(crawl.status, crawl.error)
all_pages = crawl.pages
page = client.webgrph.get_crawl_pages(crawl.crawl_id, limit=100)   # one page, by cursor
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

Extraction schemas are the shorthand `{"field": "css:selector"}` (the
`css:` prefix is optional), a list of fields
`[{"name": "link", "selector": "a", "attribute": "href"}]`, or a full
`schema_spec` with `fields`.

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
