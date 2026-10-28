"""
KLOAKD Python SDK — Quickstart

Demonstrates the artifact chaining pattern: modules compose like Unix pipes.
The output of one module (artifact_id) becomes the input to the next,
eliminating redundant HTTP round-trips.

webgrph.crawl() starts the crawl and waits until it finishes (the API
answers 202 and crawls in the background; the SDK polls for you). Use
webgrph.crawl_stream() for its progress events instead.

Run:
    pip install kloakd-sdk
    KLOAKD_API_KEY=sk-live-... KLOAKD_ORG_ID=your-org-id python examples/quickstart.py
"""

import os

from kloakd import Kloakd

client = Kloakd(
    api_key=os.environ["KLOAKD_API_KEY"],
    organization_id=os.environ["KLOAKD_ORG_ID"],
)

TARGET = "https://books.toscrape.com"

# ── Step 1: Anti-bot fetch ────────────────────────────────────────────────────
print(f"Fetching {TARGET} ...")
fetch = client.evadr.fetch(TARGET)
print(f"  tier_used={fetch.tier_used}  bypassed={fetch.anti_bot_bypassed}  artifact={fetch.artifact_id}")

# ── Step 2: Site hierarchy (waits until the crawl finishes) ──────────────────
print("Crawling site hierarchy ...")
crawl = client.webgrph.crawl(TARGET, max_depth=2, max_pages=50)
print(f"  crawl {crawl.crawl_id}: {crawl.status}, {crawl.total_pages} pages")
if not crawl.ok:
    raise SystemExit(f"  crawl failed: {crawl.error}")

# ── Step 3: Store the site ─────────────────────────────────────────────────────
print("Storing the site ...")
site = client.skanyr.site_from_crawl(crawl.crawl_id)  # reuse the crawl
print(f"  site={site.get('site_id')}")

# ── Step 4: Extract structured data ───────────────────────────────────────────
print("Extracting book data ...")
data = client.kolektr.page(
    TARGET,
    schema={
        "title": "css:h3 a",
        "price": "css:p.price_color",
        "rating": "css:p.star-rating",
    },
    fetch_artifact_id=fetch.artifact_id,  # reuse — no third fetch
)
print(f"  records={data.total_records}  method={data.method}")

# ── Step 5: Print results ──────────────────────────────────────────────────────
print("\nFirst 3 books:")
for book in data.records[:3]:
    print(f"  {book}")

# ── Bonus: Deduplication ───────────────────────────────────────────────────────
if data.records:
    seen = client.fetchyr.check_duplicate(TARGET)
    print(f"\nAlready seen: {seen.is_duplicate}")
