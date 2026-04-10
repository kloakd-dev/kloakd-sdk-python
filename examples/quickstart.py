"""
KLOAKD Python SDK — Quickstart

Demonstrates the artifact chaining pattern: modules compose like Unix pipes.
The output of one module (artifact_id) becomes the input to the next,
eliminating redundant HTTP round-trips.

Run:
    pip install kloakd-sdk
    KLOAKD_API_KEY=sk-live-... KLOAKD_ORG_ID=your-org-id python examples/quickstart.py
"""

import os

from kloakd import Kloakd
from kloakd.errors import KloakdError

client = Kloakd(
    api_key=os.environ["KLOAKD_API_KEY"],
    organization_id=os.environ["KLOAKD_ORG_ID"],
)

TARGET = "https://books.toscrape.com"

# ── Step 1: Anti-bot fetch ────────────────────────────────────────────────────
print(f"Fetching {TARGET} ...")
fetch = client.evadr.fetch(TARGET)
print(f"  tier_used={fetch.tier_used}  bypassed={fetch.anti_bot_bypassed}  artifact={fetch.artifact_id}")

# ── Step 2: Site hierarchy ─────────────────────────────────────────────────────
print("Crawling site hierarchy ...")
crawl = client.webgrph.crawl(
    TARGET,
    max_depth=2,
    max_pages=50,
    session_artifact_id=fetch.artifact_id,  # reuse — no double-fetch
)
print(f"  pages_found={crawl.total_pages}  artifact={crawl.artifact_id}")

# ── Step 3: API discovery ──────────────────────────────────────────────────────
print("Discovering APIs ...")
discovery = client.skanyr.discover(
    TARGET,
    site_hierarchy_artifact_id=crawl.artifact_id,  # reuse — skip Phase 1 crawl
)
print(f"  endpoints_found={discovery.total_endpoints}")

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
    dedup = client.fetchyr.check_duplicates(data.records, domain=TARGET)
    print(f"\nDeduplication: {dedup.duplicate_count} duplicates removed, {len(dedup.unique_records)} unique")
