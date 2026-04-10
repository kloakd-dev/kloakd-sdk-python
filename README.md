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
| `client.skanyr` | Skanyr | Two-phase API discovery |
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

fetchyr.login()  → artifact_id (AUTHENTICATED_SESSION)
  └─→ evadr.fetch(session_artifact_id=...)      # authenticated fetch
  └─→ webgrph.crawl(session_artifact_id=...)

webgrph.crawl()  → artifact_id (SITE_HIERARCHY)
  └─→ skanyr.discover(site_hierarchy_artifact_id=...)   # skip Phase 1

skanyr.discover() → artifact_id (API_MAP)
  └─→ kolektr.page(api_map_artifact_id=...)     # API-backed extraction
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
    async with client.webgrph.crawl_stream("https://books.toscrape.com") as events:
        async for event in events:
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
| `RateLimitError` | 429 | Quota exceeded (has `retry_after` seconds) |
| `UpstreamError` | 502 | Target site unreachable |
| `ApiError` | 4xx/5xx | Any other API error |

## Pagination

```python
# Manual pagination
result = client.skanyr.discover("https://api.example.com", limit=100, offset=0)
print(result.has_more, result.total)

# Auto-paginate (recommended)
all_endpoints = client.skanyr.discover_all("https://api.example.com")
all_records   = client.kolektr.page_all("https://example.com")
all_pages     = client.webgrph.crawl_all("https://example.com")
```

## Fetchyr — RPA & Authentication

```python
# Login and produce a reusable session
session = client.fetchyr.login(
    url="https://app.example.com/login",
    username_selector="#email",
    password_selector="#password",
    username="user@example.com",
    password="secret",
)

# Detect and handle MFA
mfa = client.fetchyr.detect_mfa("https://app.example.com/mfa",
                                  session_artifact_id=session.artifact_id)
if mfa.mfa_detected:
    result = client.fetchyr.submit_mfa(mfa.challenge_id, code="123456")

# Detect forms, run workflows, deduplicate records
forms  = client.fetchyr.detect_forms("https://example.com/signup")
dedup  = client.fetchyr.check_duplicates(records, domain="example.com")
```

## Links

- **Documentation:** https://docs.kloakd.dev/sdk/python
- **API Reference:** https://docs.kloakd.dev/api
- **Dashboard:** https://app.kloakd.dev
- **GitHub:** https://github.com/kloakd/kloakd-sdk-python
- **PyPI:** https://pypi.org/project/kloakd-sdk/

## License

MIT
