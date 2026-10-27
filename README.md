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

# Step 2: Crawl site hierarchy — reuse the Evadr artifact, no double-fetch
crawl = client.webgrph.crawl(
    "https://books.toscrape.com",
    max_depth=2,
    session_artifact_id=fetch.artifact_id,
)
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
  └─→ webgrph.crawl(session_artifact_id=...)    # authenticated crawl

fetchyr.authenticate() → artifact_id (AUTHENTICATED_SESSION)
  └─→ evadr.fetch(session_artifact_id=...)      # authenticated fetch
  └─→ webgrph.crawl(session_artifact_id=...)

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

    # SSE stream
    async for event in client.webgrph.crawl_stream("https://books.toscrape.com"):
        print(event.type, event.url)
```

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
| `NotEntitledError` | 403 | Plan doesn't include this module |
| `PaymentRequiredError` | 402 | The plan's last payment failed |
| `QuotaExceededError` | 429 | GB allocation and top-ups used up (`gb_exhausted`; not retried) |
| `RateLimitError` | 429 | Request rate exceeded (has `retry_after` seconds; retried) |
| `UpstreamError` | 502 | Target site unreachable |
| `BillingUnavailableError` | 503 | Usage could not be checked; retried after `retry_after` |
| `JobFailedError` / `JobTimeoutError` | — | A fetch job or crawl failed, or was still running when the wait ran out |
| `ApiError` | 4xx/5xx | Any other API error |

**Long fetches:** the API answers a synchronous fetch within about 85
seconds; one still running then continues as a job (HTTP 202).
`evadr.fetch` follows it to its result (`poll_interval`, `poll_timeout`).

## Crawls and pages

```python
crawl = client.webgrph.crawl("https://example.com")   # waits, then loads every page
all_pages = crawl.pages
page = client.webgrph.get_crawl_pages(crawl.crawl_id, limit=100)   # one page, by cursor
all_records = client.kolektr.page_all("https://example.com")
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
- **GitHub:** https://github.com/kloakd/kloakd-sdk-python
- **PyPI:** https://pypi.org/project/kloakd-sdk/

## License

MIT
